import sys
import socket
import select
import time
import Queue
import simplejson
import logging
import threading
import fcntl
import struct

REQ_SETUP_RTUNNEL   = 1
REQ_CANCL_RTUNNEL   = 2
REQ_SETUP_FWD_CNN   = 3
RSP_SETUP_RTUNNEL   = 10
RSP_SETUP_FWD_CNN   = 11
FWD_DATA            = 15

def get_ip_address():
    ifname = 'eth0'
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    return socket.inet_ntoa(fcntl.ioctl(
                    s.fileno(),
                    0x8915, #socket.SIOCGIFADDR,
                    struct.pack('256s', ifname[:15])
             )[20:24])
    
def Singleton(cls):
    instances = {}
    def get_instance():
        if cls not in instances:
            instances[cls] = cls()
        return instances[cls]
    return get_instance

class Log:
    logger = None

    def __init__(self, module="rtunnel", level=logging.DEBUG):
        self.logger = logging.getLogger(module)
        self.logger.setLevel(level)

        ch = logging.StreamHandler()
        ch.setLevel(level)

        fmter = logging.Formatter('[%(name)s]: %(message)s')
        ch.setFormatter(fmter)
        self.logger.addHandler(ch)

    def log(self, msg):
        self.logger.info(msg)

class MapT:
    map_l_r = None   #{local_idx1: remote_idx1, local_idx2: remote_idx2,...}
    map_r_l = None   #{remote_idx1: local_idx1, remote_idx2: local_idx2,...}

    def __init__(self):
        self.map_l_r = {}
        self.map_r_l = {}

    def append(self, local, remote):
        self.map_l_r[local] = remote
        self.map_r_l[remote] = local

    def remvove(self, local):
        remote = self.map_l_r.pop(local)
        self.map_r_l.pop(remote)

    def get_local(self, remote):
        return self.map_r_l[remote]

    def get_remote(self, local):
        return self.map_l_r[local]

    def dump(self):
        print "[MapT] map_l_r: ", self.map_l_r
        print "[MapT] map_r_l: ", self.map_r_l
        

@Singleton
class FdSetWrapper:
    rfdset = []
    wfdset = []
    efdset = []

    def __init__(self): pass

    def append(self, sock, category):
        {
            'r': lambda sock: self.rfdset.append(sock),
            'w': lambda sock: self.wfdset.append(sock),
            'e': lambda sock: self.efdset.append(sock)
        } [category](sock)

    def remove(self, sock, category):
        {
            'r': lambda sock: self.rfdset.remove(sock),
            'w': lambda sock: self.wfdset.remove(sock),
            'e': lambda sock: self.efdset.remove(sock)
        } [category](sock)

    def get(self, category):
        result = {
            'r': lambda: self.rfdset,
            'w': lambda: self.wfdset,
            'e': lambda: self.efdset
        } [category]()
        return result

    def dump(self):
        print "[FdSetWrapper]: rfdset: ", self.rfdset
        print "[FdSetWrapper]: wfdset: ", self.wfdset
        print "[FdSetWrapper]: efdset: ", self.efdset


@Singleton
class Container: 
    storage = {} #{0: [sck1, obj1], 1:[sck2, obj2], ...}
    sck_idx = {} #{sck1: 0, sck2: 1, ...}
    idx = 0

    relay_channels = {}

    def __init__(self): pass

    def append(self, socket):
        self.storage[self.idx] = [socket.get(), socket]
        self.sck_idx[socket.get()] = self.idx
        self.idx += 1

    def remove(self, idx):
        [sck, obj] = self.storage.pop(idx)
        self.sck_idx.pop(sck)

    def append_relay_channel(self, idx, socket):
        relay_channels[idx] = socket

    def get_by_idx(self, idx):
        return self.storage[idx][1]

    def get_by_sck(self, sck):
        return self.storage[self.sck_idx[sck]][1]

    def get_idx(self, sck):
        return self.sck_idx[sck]
        
    def dump(self):
        print "[Container]: storage: ", self.storage
        print "[Container]: sck_idx: ", self.sck_idx
        print "[Container]: cur idx: ", self.idx

class Channel(object):
    socket = None

    def __init__(self):  pass

    ## the construct suits for client that actively connect to server  
    def socket_c(self, connecting_addr):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.connect(connecting_addr)

    ## the construct suits for client accepted by listening server
    def socket_c_on_accept(self, listening_socket):
        self.socket, addr = listening_socket.accept()
        self.socket.setblocking(False)

    ## the construct suits for server that want to keep listenning on port.
    def socket_s(self, binding_addr):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.setblocking(False)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR,1)
        (binding_host, port) = binding_addr
        print "binding_host:", binding_host
        print "binding_port:", port
        if binding_host == '0.0.0.0':
            binding_host= get_ip_address()
            binding_addr = (binding_host, port)
            print "bind_addr: ", binding_addr
        self.socket.bind(binding_addr)
        self.socket.listen(10)

    def raw_send(self,data):
        self.socket.send(data)

    def raw_recv(self):
        return self.socket.recv(1024)

    def get(self):
        return self.socket

    def set_pending(self, category):
        get_fdset().append(self.socket, category)

    def clear_pending(self, category):
        get_fdset().remove(self.socket, category)

    def dump(self):
        print "[RawSocket] socket:", self.socket, " key: ", self.key
        print "[RawSocket] fdset :", fdset

class SProxyChannel(Channel):
    msgQ    = None
    logger  = None

    def __init__(self):
        self.msgQ = Queue.Queue()
        self.logger = Log("SProxyChannel")

    def prepare(self, remote_addr):
        self.socket_c(remote_addr)
        self.set_pending('r')
        get_container().append(self)
        self.logger.log("Connected to remote server")

    def send(self):
        try: msg = self.msgQ.get_nowait()
        except: 
            self.logger.log("No message in msgQ")
            self.clear_pending('w')
        else:
            self.raw_send(msg)
            self.logger.log("Send a msg: %s"%msg)
            
    def recv(self):
        data = self.raw_recv()
        if not data:
            self.logger.log("No data received.")
            self.clear_pending('r')
        else:
            self.logger.log("Received a msg: %s"%data)
            idx = get_container().get_idx(self.get())
            get_box_channel().prep_fwd_data(idx, data)

    def error(self): pass
        #todo

    def prep_send_data(self, data):
        self.msgQ.put(data) 
        self.set_pending('w')
        self.logger.log("Prepared to forward data.")

@Singleton
class BoxChannel(Channel):
    msgQ   = None
    mapT   = None
    logger = None

    # the ultimate remote server address that client will connect to.
    remote_addr = None 

    def __init__(self):
        self.msgQ = Queue.Queue()
        self.mapT = MapT()
        self.logger = Log("BoxChannel")

    def prepare(self, server_addr):
        self.socket_c(server_addr)
        self.set_pending('r')
        get_container().append(self)
        self.logger.log("Box Connected to relay.")

    def send(self):
        try: msg = self.msgQ.get_nowait()
        except:
            self.logger.log("No message in msgQ")
            self.clear_pending('w')
        else:
            self.raw_send(msg)
            self.logger.log("Send a msg: %s"%msg)

    def recv(self):
        data = self.raw_recv()
        if not data:
            self.logger.log("No data received.")
            self.clear_pending('r')
        else:
            self.logger.log("Received a msg: %s"%data)
            msg = simplejson.loads(data)
            {
                RSP_SETUP_RTUNNEL: lambda msg : self._do_rsp_setup_rtunnel(msg),
                REQ_SETUP_FWD_CNN: lambda msg : self._do_rsp_setup_fwd_cnn(msg),
                FWD_DATA         : lambda msg : self._do_rsp_fwd_data(msg)
            } [msg['0']](msg)

    def error(self): pass
        #todo

    def _do_rsp_setup_rtunnel(self, msg):
        #todo:
        # {0: RSP_SETUP_RTUNNEL, 1: True or False }
        self.logger.log("Received a response of setup rfwd")

    def _do_rsp_setup_fwd_cnn(self, msg):
        #{ 0: REQ_SETUP_FWD_CNN, 1: channel_idx }
        proxy = SProxyChannel()
        proxy.prepare(self.remote_addr)
        l_idx, r_idx  = get_container().get_idx(proxy.get()), msg['1']
        self.mapT.append(l_idx, r_idx)
        self.logger.log("Created a proxy channel to remote http server")
        self.prep_confirm_setup_fwd_cnn(l_idx, r_idx)
        self.logger.log("Prepared to confirm forward connection setup")

    def _do_rsp_fwd_data(self, msg):
        # {0: FWD_DATA , 1: corresponding channel id on box side, 2: data }        
        to_idx = self.mapT.get_local(msg['1'])
        get_container().get_by_idx(to_idx).prep_send_data(msg['2'])
        self.logger.log("Forward the data to proxy channel.")

    # this API will be called beyond the select thread.
    def prep_req_setup_rtunnel(self, listening_addr, remote_addr):
        self.remote_addr = remote_addr
        listen_host, listen_port = listening_addr
        msg = {0: REQ_SETUP_RTUNNEL,   # msg id
               1: listen_host,         # listenning host on relay side.
               2: listen_port }        # listenning port on relay side.
        self.msgQ.put(simplejson.dumps(msg))
        self.logger.log("Prepared a request to setup rtunnel")
        self.send()  

    # preapre to forward data from sproxy to common channel.
    def prep_fwd_data(self, from_idx, data):
        msg = {0: FWD_DATA,            # msg id
               1: from_idx,            # the channel id where data from.
               2: data }               # data to forward
        self.msgQ.put(simplejson.dumps(msg))
        self.set_pending('w')
        self.logger.log("Prepared to forward data from proxy.")

    def prep_confirm_setup_fwd_cnn(self, local_idx, remote_idx):
        msg = {0: RSP_SETUP_FWD_CNN,   # msg id
               1: remote_idx,          # the channel_idx of proxy channel on relay side.
               2: local_idx}           # the channel idx of proxy channel on box side
        self.msgQ.put(simplejson.dumps(msg))
        self.set_pending('w')
        self.logger.log("Prepared to confirm forward connection")

class CProxyChannel(Channel):
    msgQ    = None
    logger  = None
    idx     = 0  # idx of corresponding channel id.

    def __init__(self, relay_channel_idx):
        self.idx  = relay_channel_idx
        self.msgQ = Queue.Queue()
        self.logger = Log("CProxyChannel")

    def prepare(self, listen_socket):
        self.socket_c_on_accept(listen_socket)
        self.set_pending('r')
        get_container().append(self)
        self.logger.log("Accepted by listen rtunnel port")

    def send(self):
        try: msg = self.msgQ.get_nowait()
        except: 
            self.logger.log("No message in msgQ")
            self.clear_pending('w')
        else:
            self.raw_send(msg)
            self.logger.log("Send a msg: %s"%msg)
            
    def recv(self):
        data = self.raw_recv()
        if not data:
            self.logger.log("No data received.")
            self.clear_pending('r')
        else:
            self.logger.log("Received a msg: %s"%data)
            proxy_idx = get_container().get_idx(self.get())
            relay_chn = get_container().get_by_idx(self.idx)
            relay_chn.prep_fwd_data(proxy_idx, data)

    def error(self): pass
        #todo

    def prep_fwd_data(self, data):
        self.msgQ.put(data) 
        self.set_pending('w')
        self.logger.log("Prepared to forward data.")

class RfwdChannel(Channel):
    logger = None
    relay_chid = None

    def __init__(self, relay_channel_identifier):
        self.relay_chid = relay_channel_identifier;
        self.logger = Log("RfwChannel")

    def prepare(self, listening_addr):
        self.socket_s(listening_addr)
        self.set_pending('r')
        get_container().append(self)
        self.logger.log("Established a fwd listenning port")

    def recv(self):
        proxy = CProxyChannel(self.relay_chid)
        proxy.prepare(self.get())
        self.logger.log("Accepted a proxy connection from client")

        idx = get_container().get_idx(proxy.get())
        channel = get_container().get_by_idx(self.relay_chid)
        channel.prep_req_setup_fwd_connect(idx)

    def send(self): pass
    def error(self): pass

class RelayChannel(Channel):
    msgQ = None
    mapT = None
    logger = None
    idx  = 0 

    def __init__(self):
        self.msgQ = Queue.Queue()
        self.mapT = MapT()
        self.logger = Log("RelayChannel")

    def prepare(self, listening_socket):
        self.socket_c_on_accept(listening_socket)
        self.set_pending('r')
        get_container().append(self)
        self.idx = get_container().get_idx(self.get())
        self.logger.log("Prepared a data channel on relay side.")


    def recv(self):
        data = self.raw_recv()
        if not data:
            self.logger.log("Not data received.")
            self.clear_pending('r')
        else:
            self.logger.log("Received a msg:%s"%data)
            msg = simplejson.loads(data) 
            {
                REQ_SETUP_RTUNNEL: lambda msg: self._do_req_setup_rtunnel(msg),
                REQ_CANCL_RTUNNEL: lambda msg: self._do_req_cancl_rtuunel(msg),
                RSP_SETUP_FWD_CNN: lambda msg: self._do_rsp_setup_fwd_cnn(msg),
                FWD_DATA:          lambda msg: self._do_rsp_fwd_data(msg)
            } [msg['0']](msg)

    def send(self):
        try:
            msg = self.msgQ.get_nowait()
        except:
            self.logger.log("No message in msgQ")
            self.clear_pending('w')
        else:
            self.raw_send(msg)
            self.logger.log("Send a msg:%s"%msg)

    def error(self): pass
        
    def _do_req_setup_rtunnel(self, msg):
        #{0: REQ_SETUP_RTUNNEL, 1: listenning_host, 2: listenning_port }
        rfwd = RfwdChannel(self.idx)
        rfwd.prepare((msg['1'], msg['2'])) # listening (addr, port) to forward.
        self.prep_confirm_setup_rtunnel(msg)

    def _do_req_cancl_rtunnel(self, msg):
        #{0: REQ_CANCEL_RTUNNEL, 1: listenning_host, 2: listenning_port }
        self.logger.log("Todo <_do_cancel_rtunnel")

    def _do_rsp_setup_fwd_cnn(self, msg):
        #{0: RSP_SETUP_FWD_CNN,  1: channel_idx in on Box, 2: channel id on Relay }
        self.mapT.append(msg['1'], msg['2'])
        self.logger.log("Succeeded to setup the forward connection.")

    def _do_rsp_fwd_data(self, msg):
        #{0: FWD_DATA, 1: corresponding remote channel id,  2:data }
        to_idx = self.mapT.get_local(msg['1'])
        get_container().get_by_idx(to_idx).prep_fwd_data(msg['2'])
        self.logger.log("Prepared to forward data to cproxy.")

    def prep_confirm_setup_rtunnel(self, msg):
        newmsg= {0: RSP_SETUP_RTUNNEL,  # msg id
                 1: msg['1'],           # listenning_addr,
                 2: msg['2'],           # listenning_port,
                 3: True }              # success(True) or failure(False)
        self.msgQ.put(simplejson.dumps(newmsg))
        self.set_pending('w')
        self.logger.log("The remote fwd listening port is ready")

    def prep_fwd_data(self, proxy_idx, data):
        msg = {0: FWD_DATA,             # msg id 
               1: proxy_idx,            # local channel id on box side. 
               2: data }                # data to forward
        self.msgQ.put(simplejson.dumps(msg))
        self.set_pending('w')
        self.logger.log("Prepared the forward data")

    def prep_req_setup_fwd_connect(self, channel_idx):
        msg = {0: REQ_SETUP_FWD_CNN,    # msg id
               1: channel_idx }         # corresponding channel id on relay side.
        self.msgQ.put(simplejson.dumps(msg))
        self.set_pending('w')
        self.logger.log("Prepared the request to setup froward connection")

@Singleton        
class ServerChannel(Channel):
    logger     = None
    constraint = True
    denied     = False

    def __init__(self): 
        self.logger = Log("ServerChannel")

    #@constraint: indicate whether only one client connection is allowed.
    def prepare(self, binding_addr, constraint=True):
        self.constraint = constraint
        self.socket_s(binding_addr)
        self.set_pending('r')
        get_container().append(self)
        self.logger.log("Builded a server channel for listenning connection")

    def send(self): pass
    def recv(self): 
        # there will be more connections from different box.
        if self.constraint and self.denied:
            pass
        else:
            RelayChannel().prepare(self.get())
            if not self.constraint:
                self.denied = True
            self.logger.log("Established a relay channel connected by box.")
        
    def error(self): pass

#-----------------------------------------------------------------------
@Singleton
class Poller:
    logger = None

    def __init__(self):
        self.logger = Log("ChannelPoller")
        self.thread = threading.Thread(target=self.poll_process)

    def poll_process(self):
        while True:

            rs,ws,es = select.select(get_fdset().get('r'),
                                     get_fdset().get('w'),
                                     get_fdset().get('e'), 6000)
            if not (rs or ws or es):
                print "[ Box  ] timeout ..."
                continue

            for s in rs:
                get_container().get_by_sck(s).recv()

            for s in ws:
                get_container().get_by_sck(s).send()

            for s in es:
                get_container().get_by_sck(s).send()
                get_container().get_by_sck(s).error()

    def start(self):
        self.thread.start()
        self.logger.log("Started the poller thread")

    def join(self):
        self.thread.join()

#-------------------------------------------------------------------------
def get_fdset():
    return FdSetWrapper()

def get_container():
    return Container()

def get_box_channel():
    return BoxChannel()

def get_poller():
    return Poller()

#-------------------------------------------------------------------------

#  init the running envrionment for reverse tunnel 
#  this API will internally create a working thread that keeps polling all channels 
#  @binding_address   : the address to bind as being server with relay fucntion.
#                       "0.0.0.0" means the IPv4 address of this machine.
#  @connection_address: the address to connnec as being box 

def init_rtunnel(binding_addr, connection_addr):
    ServerChannel().prepare(binding_addr)
    get_box_channel().prepare(connection_addr)
    get_poller().start()

#  request to setup the remote port forward on a given address
#  @ listenning_address : the address on which the connection will forward
#                         "0.0.0.0" means the IPv4 address of this machine.
#  @ remote_address     : the server address at which the data send from client
#                         will ultimately arrive
def req_setup_remote_forward(listenning_addr, remote_addr):
    get_box_channel().prep_req_setup_rtunnel(listenning_addr, remote_addr)


def init_relay_simulator(binding_addr):
    ServerChannel().prepare(binding_addr)
    get_poller().start()
#------------------------------------------------------------------------
def dump_usage():
    print "box.py --relay --binding='host:port' "
    print "or"
    print "box.py --box   --binding='host:port' --forward='host:port' --connection='host:port' --remote='host:port"
    print ""
    
#-----------------------------------------------------------------------
if __name__ == "__main__":
    is_relay = False
    bind_addr       = None
    forward_addr    = None
    connection_addr = None
    remote_addr     = None

    if len(sys.argv) < 2:
        dump_usage()
        exit(-1)
    else:
        if sys.argv[1] == "--relay":
            is_relay = True
        elif sys.argv[1] == "--box":
            is_relay = False
        else:
            dump_usage()
            exit(-1)

        for argv in sys.argv[2:]:
            prefix = argv.split('=')[0]
            value  = argv.split('=')[1]

            if prefix == "--bind":
                bind_addr = (value.split(':')[0], int(value.split(':')[1]))
            elif prefix == '--forward':
                forward_addr = (value.split(':')[0], int(value.split(':')[1]))
            elif prefix == '--connection':
                connection_addr= (value.split(':')[0], int(value.split(':')[1]))
            elif prefix == '--remote':
                remote_addr = (value.split(':')[0], int(value.split(':')[1]))
            else:
                dump_usage()
                exit(-1)
        print "bind: ", bind_addr
        print "forward: ",forward_addr 
        print "connection: ",connection_addr
        print "remote: ",remote_addr
                

    if is_relay:
        print "Purely relay simulated."
        init_relay_simulator(bind_addr)
    else:  
        print "Box with relay limited function"
        init_rtunnel(bind_addr, connection_addr)
        time.sleep(0.5)
    #    time.sleep(1)
        req_setup_remote_forward(forward_addr, remote_addr)

    get_poller().join()


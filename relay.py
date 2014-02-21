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
    channels = {}

    def __init__(self): pass
    def append(self, channel):
	self.channels[channel.get_fd()] = channel

#    def remove(self, socket):
#        del self.channels[socket]

    def get(self, socket_fd):
	return self.channels[socket_fd]

class Channel(object):
    socket = None
    idx = 0

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

    def get_fd(self):
	return self.socket.fileno()

    def set_pending(self, category):
        get_fdset().append(self.socket, category)

    def clear_pending(self, category):
        get_fdset().remove(self.socket, category)

    def dump(self):
        print "[RawSocket] socket:", self.socket, " key: ", self.key
        print "[RawSocket] fdset :", fdset

class ClientChannel(Channel):
    msgQ    = None
    logger  = None
    relay_socket_fd = None

    def __init__(self, relay_socket_fd):
	self.relay_socket_fd = relay_socket_fd
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
	    relay_chan = get_container().get(self.relay_socket_fd)
            relay_chan.prep_fwd_data(self.get_fd(), data)
            
    def error(self): pass
        #todo

    def prep_fwd_data(self, data):
        self.msgQ.put(data) 
        self.set_pending('w')
        self.logger.log("Prepared to forward data.")

class ForwardChannel(Channel):
    logger = None
    relay_socket_fd = 0

    def __init__(self, relay_socket):
        self.relay_socket_fd = relay_socket.fileno()
        self.logger = Log("ForwardChannel")

    def prepare(self, listening_addr):
        self.socket_s(listening_addr)
        self.set_pending('r')
	get_container().append(self)
        self.logger.log("Established a fwd listenning port")

    def recv(self):
        client = ClientChannel(self.relay_socket_fd)
        client.prepare(self.get())
        self.logger.log("Accepted a proxy connection from client")
	
	relay_chan = get_container().get(self.relay_socket_fd)
	relay_chan.prep_req_setup_fwd_connect(client.get_fd())

    def send(self): pass
    def error(self): pass

class RelayChannel(Channel):
    msgQ = None
    mapT = None
    logger = None

    def __init__(self):
        self.msgQ = Queue.Queue()
        self.mapT = MapT()
        self.logger = Log("RelayChannel")

    def prepare(self, listening_socket):
        self.socket_c_on_accept(listening_socket)
        self.set_pending('r')
        get_container().append(self)
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
        rfwd = ForwardChannel(self.get())
        rfwd.prepare((msg['1'], msg['2'])) # listening (addr, port) to forward.
        self.prep_confirm_setup_rtunnel(msg)

    def _do_req_cancl_rtunnel(self, msg):
        #{0: REQ_CANCEL_RTUNNEL, 1: listenning_host, 2: listenning_port }
        self.logger.log("Todo <_do_cancel_rtunnel")

    def _do_rsp_setup_fwd_cnn(self, msg):
        #{0: RSP_SETUP_FWD_CNN, \
	    # 1: channel socket on relay side
	    # 2: channel socket on proxy side
        self.mapT.append(msg['1'], msg['2'])
        self.logger.log("Succeeded to setup the forward connection.")

    def _do_rsp_fwd_data(self, msg):
        #{0: FWD_DATA, 1: corresponding remote channel id,  2:data }
        to_sck = self.mapT.get_local(msg['1'])
        get_container().get(to_sck).prep_fwd_data(msg['2'])
        self.logger.log("Prepared to forward data to cproxy.")

    def prep_confirm_setup_rtunnel(self, msg):
        newmsg= {0: RSP_SETUP_RTUNNEL,  # msg id
                 1: msg['1'],           # listenning_addr,
                 2: msg['2'],           # listenning_port,
                 3: True }              # success(True) or failure(False)
        self.msgQ.put(simplejson.dumps(newmsg))
        self.set_pending('w')
        self.logger.log("The remote fwd listening port is ready")

    def prep_fwd_data(self, socket_fd, data):
        msg = {0: FWD_DATA,             # msg id 
               1: socket_fd,            # socket on relay side communitated with client.
               2: data }                # data to forward
        self.msgQ.put(simplejson.dumps(msg))
        self.set_pending('w')
        self.logger.log("Prepared the forward data")

    def prep_req_setup_fwd_connect(self, socket_fd):
        msg = {0: REQ_SETUP_FWD_CNN,    # msg id
               1: socket_fd}          # corresponding sock on relay side.
	print "<pre_req_setup_fwd_connect> socket_fd:", socket_fd
        self.msgQ.put(simplejson.dumps(msg))
        self.set_pending('w')
        self.logger.log("Prepared the request to setup froward connection")

## ---------------------------------------------------------------------------
## @ServerChannel: The very first server channel that relay server provides 
##  for box to connect. And for now, only one box and only one connection is
##  allowed.
## --------------------------------------------------------------------------
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
	    self.logger.log("Only one channel is allowed, you already have one.")
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
                get_container().get(s.fileno()).recv()

            for s in ws:
                get_container().get(s.fileno()).send()

            for s in es:
                get_container().get(s.fileno()).send()
                get_container().get(s.fileno()).error()

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

def get_poller():
    return Poller()

#-------------------------------------------------------------------------

#  init the running envrionment for reverse tunnel 
#  this API will internally create a working thread that keeps polling all channels 
#  @binding_address   : the address to bind as being server with relay fucntion.
#                       "0.0.0.0" means the IPv4 address of this machine.
#  @connection_address: the address to connnec as being box 

def init_relay_simulator(binding_addr):
    ServerChannel().prepare(binding_addr)
    get_poller().start()

#------------------------------------------------------------------------
def dump_usage():
    print "relay.py --binding='host:port' "
    print ""
    
#-----------------------------------------------------------------------
if __name__ == "__main__":
    bind_addr       = None

    if len(sys.argv) < 2:
        dump_usage()
        exit(-1)
    else:
        for argv in sys.argv[1:]:
            prefix = argv.split('=')[0]
            value  = argv.split('=')[1]

            if prefix == "--binding":
                bind_addr = (value.split(':')[0], int(value.split(':')[1]))
            else:
                dump_usage()
                exit(-1)
        print "binding addr: ", bind_addr

    print "Purely relay simulated starting.."
    init_relay_simulator(bind_addr)

    get_poller().join()


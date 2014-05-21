import sys

from streamingable  import *
from indexable      import *
from pollable       import *
from slottable      import *
from libconfig      import *
from message        import *
from errcode        import *

singleton_proxyed_listenning_object = None

class ClientChannel(Streamingable, Pollable, Indexable, Slottable):
    logger   = None
    creator  = None
    peer_idx = -1 
    
    def __init__(self, creator, peer_idx):
        Streamingable.__init__(self, "active", get_proxyed_config().remote_client_addr())
        Pollable .__init__(self, self.get_socket())
        Indexable.__init__(self, self.get_socket())
        Slottable.__init__(self)

        self.logger   = Log("ClientChannel")
        self.creator  = creator
        self.peer_idx = peer_idx

        self.set_indexable()
        self.set_pollable('r')
        self.set_pollable('e')
        self.register_slot(slot_fwd_data, self._routine_fwd_data_2_server)
        self.register_slot(slot_error   , self._routine_error            )

    def send(self): 
        ecode = Streamingable.send(self)
        if ecode == ecode_empty_queue or ecode == ecode_ok:
            self.clear_pollable('w')
            self.set_pollable('r')
        elif ecode == ecode_try_again:
            pass #send again
        else:
            self.logger.log("[send](error:%s)"%ecode_string(ecode))

    def recv(self): 
        ecode, data = Streamingable.recv(self)
        if ecode != ecode_ok:
            self.logger.log("[recv](error:%s)"%ecode_string(ecode))
        elif not data:
            self.clear_pollable('r')
        elif self.peer_idx < 0:
            pass
        else:
            attrs = {attr_peer_idx: self.peer_idx, attr_data: data }
            self.creator.signal_slot(slot_fwd_data, attrs)

    def error(self, infected=False):
        self.logger.log("[error]")
        if not infected:
            attrs = {attr_client_idx: self.get_idx()}
            self.creator.signal_slot(slot_reclaim_channel, attrs) 
        self._shutdown()

    def _routine_fwd_data_2_server(self, attrs):
        data = get_attr_val(attrs, attr_data)
        if data:
            self.put_msg(data)
            self.set_pollable('w')

    def _routine_error(self, attrs):
        self.error(self, True)

    def _shutdown(self):
        self.unregister_slots()
        self.clear_indexable()
        self.clear_pollable()
        self.close()

class ProxyedChannel(Streamingable, Pollable, Indexable, Slottable):
    logger  = None
    clients = None

    def __init__(self):
        Streamingable.__init__(self, "active", get_proxyed_config().relay_server_addr())
        Pollable .__init__(self, self.get_socket())
        Indexable.__init__(self, self.get_socket())
        Slottable.__init__(self)

        self.logger = Log("ProxyedChannel")
        self.clients = []

        self.set_indexable()
        self.set_pollable('r')
        self.set_pollable('e')
        self.register_slot(slot_fwd_data       , self._routine_fwd_data_2_peer)
        self.register_slot(slot_reclaim_channel, self._routine_reclaim_client )
        self.register_slot(slot_bind_relay     , self._routine_req_bind_relay )
        self.register_slot(slot_error          , self._routine_error          )
        
    def send(self):
        ecode = Streamingable.send(self)
        if ecode == ecode_empty_queue or ecode == ecode_ok:
            self.logger.log("[send] ecode:%d"%ecode)
            self.clear_pollable('w')
            self.set_pollable('r')
        elif ecode_try_again:
            pass # send again
        else:
            self.logger.log("[send](error:%s)"%code_string(ecode))
        
    def recv(self):
        ecode, data = Streamingable.recv(self)
        if ecode != ecode_ok:
            self.logger.log("[recv](error:%s)"%ecode_string(ecode))
        if not data:
            self.clear_pollable('w')
        else:
            msg = InMsg(data)
            if not msg.unpack():
                self.logger.log("[recv] bad msg format, skipped")
            if msg.method() == method_bind_relay:
                self.bind_relay_facility(msg)
            elif msg.method() == method_bind_channel:
                self.bind_channel_facility(msg) 
            elif msg.method() == method_fwd_data:
                self.fwd_data_2_server(msg) 
            else:
                self.logger.log("[recv] unappreciated method:%d"%msg.method())

    def error(self, infected=False):
        self.logger.log("[error]")
        for idx in self.clients:
            client = get_channel_indexer().get(idx)
            if client:
                client.signal_slot(slot_error, None)

        if not infected:
            get_channel_laundry().signal_slot(slot_reclaim_channel, None)
        self._shutdown()

    def bind_relay_facility(self, msg):
        mclass  = msg.mclass()
        transid = msg.transid()
        attrs   = msg.attrs()

        if not is_rsp_class(mclass):
            self.logger.log("[bind_relay_facility] bad mclass(%d)"%mclass)
        elif mclass == mclass_rsp_err:
            error = attr_get_val(attrs, attr_error)
            self.logger.log("[bind_relay_facility] bind relay failed(%s)"%error_string(error))
        else: #todo for transid
            self.logger.log("[bind_relay_facility] bind relay succeeded")

    def bind_channel_facility(self, msg): 
        mclass  = msg.mclass()
        transid = msg.transid()
        attrs   = msg.attrs()
        idx     = get_attr_val(attrs, attr_peer_idx)

        if mclass != mclass_request:
            self.logger.log("[bind_channel_facility] bad mclass(%d)"%mclass)
        elif not idx or idx < 0:
            self.logger.log("[bind_channel_facility] bad peer idx")
            attrs = {attr_error: error_bad_peer_idx}
            out = OutMsg(method_bind_channel, mclass_rsp_err, transid).add_attrs(attrs)
        else:
            client = ClientChannel(self, idx)
            self.clients.append(client.get_idx())

            attrs = {attr_client_idx:client.get_idx(), attr_peer_idx:idx} 
            out = OutMsg(method_bind_channel, mclass_rsp_suc, transid).add_attrs(attrs)
            self.logger.log("[bind_channel_facility] bounded channel")

        if out and out.pack():
            self.put_msg(out.to_buf())
            self.set_pollable('w')
            
    def fwd_data_2_server(self, msg):
        mclass  = msg.mclass()
        transid = msg.transid()
        attrs   = msg.attrs()
        idx     = get_attr_val(attrs, attr_client_idx)
        data    = get_attr_val(attrs, attr_data)

        if mclass != mclass_indication:
            self.logger.log("[fwd_data_2_server] bad mclass(%d)"%mclass)
        elif not idx or idx < 0 or idx not in self.clients:
            self.logger.log("[fwd_data_2_server] bad client idx")
        elif not data:
            self.logger.log("[fwd_data_2_server] msg without data attr.")
        else: 
            client = get_channel_indexer().get(idx)
            if client:
                client.put_msg(data)
                client.set_pollable('w')

    def _routine_req_bind_relay(self, attrs):
        self.logger.log("[_routine_req_bind_relay]")
        msg = OutMsg(method_bind_relay, mclass_request).add_attrs(attrs)
        if msg.pack():
            self.put_msg(msg.to_buf())
            self.set_pollable('w')
            self.send() 
                
    def _routine_fwd_data_2_peer(self, attrs):
        self.logger.log("[_routine_fwd_data_2_peer]")
        msg = OutMsg(method_fwd_data, mclass_indication).add_attrs(attrs)
        if msg.pack():
            self.put_msg(msg.to_buf())
            self.set_pollable('w')

    def _routine_reclaim_client(self, attrs):
        self.logger.log("[_routine_reclaim_client]")
        idx = get_attr_val(attrs, attr_client_idx)
        if idx and idx in self.clients:
            self.clients.remove(idx)

    def _routine_error(self, attrs):
        self.logger.log("[_routine_error]")
        self.error(True)

    def _shutdown(self):
        self.unregister_slots()
        self.clear_pollable()
        self.clear_indexable()
        self.close()

    @staticmethod
    def singleton():
        global singleton_proxyed_listenning_object
        if not singleton_proxyed_listenning_object:
            singleton_proxyed_listenning_object = ProxyedChannel()
        return singleton_proxyed_listenning_object

def get_channel_proxy():
    return ProxyedChannel.singleton()

def init_proxy():
    proxy = get_channel_proxy()
    if not proxy:
        return False

    host, port = get_proxyed_config().relay_service_addr()
    attrs = {attr_address: host + ":" + str(port), attr_software: "pyproxy"}
    proxy.signal_slot(slot_bind_relay, attrs)
    return True


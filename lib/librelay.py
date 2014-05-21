import sys

from listenningable import *
from streamingable  import *
from indexable      import *
from pollable       import *
from slottable      import *
from libconfig      import *
from liblogger      import *
from message        import *


singleton_relayed_listenning_object = None

class PeeredChannel(Streamingable, Pollable, Indexable, Slottable):
    logger = None

    client_idx = -1
    creator = None
    relay   = None
    
    def __init__(self, creator, relay):
        Streamingable.__init__(self, "passive", creator.get_socket())
        Pollable .__init__(self, self.get_socket())
        Indexable.__init__(self, self.get_socket())
        Slottable.__init__(self)
        
        self.logger  = Log("PeeredChannel")
        self.creator = creator
        self.relay   = relay
    
        self.set_indexable()
        self.set_pollable('r')
        self.set_pollable('e')
        self.register_slot(slot_fwd_data  , self._routine_fwd_data_2_peer)
        self.register_slot(slot_set_cookie, self._routine_set_client_idx )
        self.register_slot(slot_error     , self._routine_error          )

    def send(self):
        ecode = Streamingable.send(self)
        if ecode == ecode_empty_queue or ecode == ecode_ok:
            self.clear_pollable('w')
            self.set_pollable('r')
        elif ecode == ecode_try_again:
            pass # send again.
        else:
            self.logger.log("[send](error:%s)"%ecode_string(ecode))
 
    def recv(self):
        ecode, data = Streamingable.recv(self)
        if ecode != ecode_ok:
            self.logger.log("[recv](error:%s)"%ecode_string(ecode))
        elif not data:
            self.clear_pollable('r')
        elif self.client_idx < 0:
            self.logger.log("[recv] not bounded channel")
        else:
            attrs = {attr_client_idx: self.client_idx, attr_data: data}
            self.relay.signal_slot(slot_fwd_data, attrs)
            
    def error(self, infected=False): 
        self.logger.log("[error]")
        if not infected:
            attrs = {attr_peer_idx: self.get_idx()}
            self.creator.signal_slot(slot_reclaim_channel, attrs)
        self._shutdown()

    def _routine_fwd_data_2_peer(self, attrs):
        data = get_attr_val(attrs, attr_data)
        if data:
            self.put_msg(data)
            self.set_pollable('w')
    
    def _routine_set_client_idx(self, attrs):
        idx = get_attr_val(attrs, attr_client_idx)
        if idx and idx > 0:
            self.client_idx = idx

    def _routine_error(self, attrs):
        self.error(True)

    def _shutdown(self):
        self.unregister_slots()
        self.clear_indexable()
        self.clear_pollable()
        self.close()

class PeeredListenningChannel(Listenningable, Pollable, Indexable, Slottable):
    logger  = None
    creator = None
    peers   = None

    cur_peers = 0
    max_peers = 5

    def __init__(self, creator, binding_addr):
        Listenningable.__init__(self, binding_addr)
        Pollable  .__init__(self, self.get_socket())
        Indexable .__init__(self, self.get_socket())
        Slottable .__init__(self)

        self.logger   = Log("PeeredListeningChannel")
        self.creator = creator
        self.peers   = []
        self.max_peers = get_relayed_config().max_peer_connections_per_client()
        
        self.set_indexable()
        self.set_pollable('r')
        self.set_pollable('e')
        self.register_slot(slot_reclaim_channel, self._routine_reclaim_channel)
        self.register_slot(slot_error          , self._routine_error          )

    def send(self): 
        pass

    def recv(self):
        if self.cur_peers < self.max_peers:
            self.cur_peers += 1
            peer = PeeredChannel(self, self.creator)
            self.peers.append(peer.get_idx())

            attrs = {attr_peer_idx: peer.get_idx()}
            self.creator.signal_slot(slot_bind_channel, attrs)
        else:
            self.clear_pollable('r')
            self.logger.log("[recv]: exceeded connectionss")

    def error(self, infected=False):
        self.logger.log("[error]")
        for peer_idx in self.peers:
            peer = get_channel_indexer().get(peer_idx)
            if peer:
                peer.signal_slot(slot_error, None)

        if not infected:
            attrs = {attr_channel_idx: self.get_idx()}
            self.creator.signal_slot(slot_reclaim_channel, attrs)
        self._shutdown()

    def _routine_reclaim_channel(self, attrs):
        idx = get_attr_val(attrs, attr_peer_idx)
        if idx and idx in self.peers:
            self.peers.remove(idx)
            self.set_pollable('r')
            self.cur_peers -= 1


    def _routine_error(self, attrs):
        self.error(True)

    def _shutdown(self):
        self.unregister_slots()
        self.clear_indexable()
        self.clear_pollable()
        self.close()
        

class RelayedChannel(Streamingable, Pollable, Indexable, Slottable):
    logger  = None
    creator = None

    peer_l  = None

    def __init__(self, creator):
        Streamingable.__init__(self, "passive", creator.get_socket())
        Pollable .__init__(self, self.get_socket())
        Indexable.__init__(self, self.get_socket())
        Slottable.__init__(self)

        self.logger  = Log("RelayedChannel")
        self.creator = creator
    
        self.set_indexable()
        self.set_pollable('r')
        self.set_pollable('e')
        self.register_slot(slot_fwd_data       , self._routine_fwd_data_2_client)
        self.register_slot(slot_reclaim_channel, self._routine_reclaim_channel  )
        self.register_slot(slot_bind_channel   , self._routine_bind_channel     )
        self.register_slot(slot_error          , self._routine_error            )

    def send(self):
        ecode = Streamingable.send(self)
        if ecode == ecode_empty_queue or ecode == ecode_ok:
            self.clear_pollable('w')
            self.set_pollable('r')
        elif ecode == ecode_try_again:
            pass # send again.
        else:
            self.logger("[send]:%s"%ecode_string(ecode))

    def recv(self):
        self.logger.log("[recv]")
        ecode, data = Streamingable.recv(self)
        if ecode != ecode_ok:
            self.logger("[recv]:%s"%ecode_string(ecode))
        elif not data:
            self.clear_pollable('r')
        else:
            msg = InMsg(data)
            if not msg.unpack():
                self.logger.log("[recv] bad msg format, skipped")
            elif msg.method() == method_bind_relay:
                self.bind_relay_facility(msg)
            elif msg.method() == method_bind_channel:
                self.bind_channel_facility(msg)
            elif msg.method() == method_fwd_data:
                self.fwd_data_2_peer(msg)
            else:
                self.logger.log("[recv] bad method(%d)"%self.method())
        
    def error(self, infected=False):
        self.logger.log("[error]")
        self.peered_l.sginal_slot(slot_error, None)
        if not infected:
            attrs = {attr_channel_idx, self.get_idx()}
            self.creator.signal_slot(slot_relaim_channel, attrs)
        self._shutdown()

    def bind_relay_facility(self, msg):
        mclass  = msg.mclass()
        transid = msg.transid()
        attrs   = msg.attrs()
        address = get_attr_val(attrs, attr_address)
        software= get_attr_val(attrs, attr_software)
    
        if mclass != mclass_request:
            self.logger.log("[bind_relay_facility] bad mclass(%d)"%mclass)
        elif not address:
            attrs = {attr_error, error_no_binding_addr}
            out = OutMsg(method_bind_relay, mclass_rsp_err, transid).add_attrs(attrs)
            self.logger.log("[bind_relay_facility] request without binding addr")
        elif self.peer_l:
            attrs = {attr_error, error_already_peered_listenning}
            out = OutMsg(method_bind_relay, mclass_rsp_err, transid).add_attrs(attrs)
            self.logger.log("[bind_relay_facility] already in peered listenning")
        else:
            host, port = address.split(':')
            self.peer_l = PeeredListenningChannel(self, (host, int(port)))
            out = OutMsg(method_bind_relay, mclass_rsp_suc, transid)

        if out and out.pack():
            self.put_msg(out.to_buf())
            self.set_pollable('w')

    def bind_channel_facility(self, msg):
        mclass  = msg.mclass()
        transid = msg.transid() 
        attrs   = msg.attrs()
        idx     = get_attr_val(attrs, attr_peer_idx)

        if not is_rsp_class(mclass): #todo for transid
            self.logger.log("[bind_channel_facility] bad mclass(%d)"%mclass)
        elif not idx or idx < 0:
            self.logger.log("[bind_channel_facility] response with bad peer_idx")
        else:
            peer = get_channel_indexer().get(idx)
            if peer and mclass == mclass_rsp_err:
                peer.signal_slot(slot_error, None)
            if peer and mclass == mclass_rsp_suc:
                peer.signal_slot(slot_set_cookie, attrs)

    def fwd_data_2_peer(self, msg):
        mclass  = msg.mclass()
        transid = msg.transid()
        attrs   = msg.attrs()
        idx     = get_attr_val(attrs, attr_peer_idx)

        if mclass != mclass_indication:
            self.logger.log("[fwd_data_2_peer] bad mclass(%d)"%mclass)
        elif not idx or idx < 0:
            self.logger.log("[fwd_data_2_peer] indication with bad peer_idx")
        else:
            peer = get_channel_indexer().get(idx)
            if peer:
                peer.signal_slot(slot_fwd_data, attrs)

    def _routine_bind_channel(self, attrs):
        msg = OutMsg(method_bind_channel, mclass_request).add_attrs(attrs)
        if msg.pack():
            self.put_msg(msg.to_buf())
            self.set_pollable('w')
        
    def _routine_fwd_data_2_client(self, attrs): 
        msg = OutMsg(method_fwd_data, mclass_indication).add_attrs(attrs)
        if msg.pack():
            self.put_msg(msg.to_buf())
            self.set_pollable('w')

    def _routine_reclaim_channel(self, attrs):
        idx = get_attr_val(attrs, attr_channel_idx)
        if idx == self.peer_l.get_idx():
            self.peer_l = None

    def _routine_error(self, attrs):
        self.error(True)

    def _shutdown(self):
        self.unregister_slots()
        self.clear_indexable()
        self.clear_pollable()
        self.close()
            
class RelayedListenningChannel(Listenningable, Pollable, Indexable, Slottable):
    logger = None
    cur_relays = 0
    max_relays = 5
    relays = None

    binding_addr = None

    def __init__(self):
        self.binding_addr = get_relayed_config().relay_server_addr()
        Listenningable.__init__(self, self.binding_addr)
        Pollable .__init__(self, self.get_socket())
        Indexable.__init__(self, self.get_socket())
        Slottable.__init__(self)

        self.logger = Log("RelayedListenningChannel")
        self.max_relays = get_relayed_config().max_client_connections()
        self.relays = []

        self.set_indexable()
        self.set_pollable('r')
        self.set_pollable('e')
        self.register_slot(slot_reclaim_channel, self._routine_reclaim_relay)
        self.register_slot(slot_error          , self._routine_error        )

    def send(self): 
        pass

    def recv(self):
        if self.cur_relays < self.max_relays:
            relay = RelayedChannel(self)
            self.relays.append(relay.get_idx())
            self.cur_relays += 1
        else:
            self.logger.log("[recv] Exceeded client connections")

    def error(self, infected=False):
        self.logger.log("[error]")
        for relay_idx in self.relays:
            relay = get_channel_indxer().get(relay_idx)
            if relay:
                relay.signal_slot(slot_error, None)
        if not infected:
            get_realyed_laundry().signal_slot(slot_reclaim_channel, None)
        self._shutdown()

    def _routine_reclaim_relay(self, attrs):
        self.logger.log("[_routine_reclaim_relay]")
        idx = get_attr_val(attrs, attr_channel_idx)
        if idx and idx in self.relays:
            self.relays.remove(idx)
            self.cur_relays -= 1

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
        global singleton_relayed_listenning_object
        if not singleton_relayed_listenning_object:
            singleton_relayed_listenning_object = RelayedListenningChannel()
        return singleton_relayed_listenning_object

def get_channel_relay():
    return RelayedListenningChannel.singleton()


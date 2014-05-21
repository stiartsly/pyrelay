import sys
import socket
import select
import logging
import threading

from slottable import *
from indexable import *
from librelay  import *
from libproxy  import *

_singleton_channellaundry_object = None

class ChannelLaundry(Slottable):
    logger  = None
    thread  = None
    channel = None
    poller  = None
    need_exit = False

    def __init__(self, relayed_side):
        Slottable.__init__(self)

        self.logger = Log("ChannelLaundry")
        self.thread = threading.Thread(target=self.laundry_routine)
        self.poller = get_channel_poller()
        if relayed_side:
            self.channel = get_channel_relay()
        else:
            self.channel = get_channel_proxy()
        self.signal_slot(slot_reclaim_channel, self._routine_recycle)
        
        
    def laundry_routine(self):
        while not self.need_exit:
            events = self.poller.poll()
            if not events:
                continue
            for event in events:
                fd, category = event
                {
                    'r': lambda fd: get_channel_indexer().get(fd).recv(),
                    'w': lambda fd: get_channel_indexer().get(fd).send(),
                    'e': lambda fd: get_channel_indexer().get(fd).error()
                } [category](fd)
                
    def boost(self):
        self.thread.start()
        self.logger.log("Started the poller thread")

    def terminate(self):
        self.need_exit = True
        self.channel.signal_slot(slot_error, None)
        self.thread.join()

    def join(self):
        self.thread.join()

    def _routine_recycle(self, attrs):
        self.need_exit = True

    @staticmethod
    def singleton(relayed_side):
        global _singleton_channellaundry_object
        if not _singleton_channellaundry_object:
            _singleton_channellaundry_object = ChannelLaundry(relayed_side)
            
        return _singleton_channellaundry_object

def get_proxyed_laundry():
    return ChannelLaundry.singleton(False)

def get_relayed_laundry():
    return ChannelLaundry.singleton(True)


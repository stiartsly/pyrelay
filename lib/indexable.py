import sys
import socket

singleton_channelindexer_object = None 

class ChannelIndexer(object):
    channels = None

    def __init__(self):
        self.channels = {}

    def get(self, idx):
        if idx in self.channels:
            return self.channels[idx]
        else:
            return None

    def append(self, idx, channel):
        self.channels[idx] = channel

    def remove(self, idx):
        if idx in self.channels:
            self.channels.pop(idx)

    @staticmethod
    def singleton():
        global singleton_channelindexer_object
        if not singleton_channelindexer_object:
            singleton_channelindexer_object = ChannelIndexer()
        return singleton_channelindexer_object 

class Indexable(object):
    socket  = None
    indexer = None

    def __init__(self, socket):
        self.socket  = socket
        self.indexer = ChannelIndexer.singleton()

    def get_idx(self):
        return self.socket.fileno()

    def set_indexable(self):
        self.indexer.append(self.get_idx(), self)

    def clear_indexable(self):
        self.indexer.remove(self.get_idx())

def get_channel_indexer():
    return ChannelIndexer.singleton()


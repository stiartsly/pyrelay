import sys
import socket
import select

singleton_channelpoller_object = None

def _return_params(params):
    return params

def _to_category(flag):
    return {
        select.EPOLLIN : lambda: _return_params('r'),
        select.EPOLLPRI: lambda: _return_params('r'),
        select.EPOLLOUT: lambda: _return_params('w'),
        select.EPOLLERR: lambda: _return_params('e'),
        select.EPOLLHUP: lambda: _return_params('e')
    }[flag]()

def _to_emasks(category):
    return {
        'r': lambda: _return_params(select.EPOLLIN  | select.EPOLLPRI),
        'w': lambda: _return_params(select.EPOLLOUT                  ),
        'e': lambda: _return_params(select.EPOLLERR | select.EPOLLHUP)
    } [ category]()

class ChannelPoller(object):
    epoller = None
    timeout = 5

    def __init__(self, timeout=50): 
        self.epoller = select.epoll()
        self.timeout = timeout

    def register(self, fd, masks):
        self.epoller.register(fd, masks)

    def modify(self, fd, masks):
        self.epoller.modify(fd, masks)

    def unregister(self, fd):
        self.epoller.unregister(fd)

    def poll(self):
        events = self.epoller.poll(self.timeout)
        result = []
        for event in events:
            result.append((event[0], _to_category(event[1])))

        return result
 
    @staticmethod
    def singleton():
        global singleton_channelpoller_object
        if not singleton_channelpoller_object:
            singleton_channelpoller_object = ChannelPoller()
        return singleton_channelpoller_object 

class Pollable(object):
    socket = None
    poller = None
    emasks = 0x0
    registered = False

    def __init__(self, socket):
        self.socket = socket
        self.poller = get_channel_poller()

    def set_pollable(self, category):
        self.emasks |= _to_emasks(category)
        fd = self.socket.fileno()

        if not self.registered:
            self.registered = True
            self.poller.register(fd, self.emasks)
        else:
            self.poller.modify(fd, self.emasks)

    def clear_pollable(self, category = None):
        fd = self.socket.fileno()
        if not category:
            self.registered = False
            self.poller.unregister(fd)
            rteurn 

        emasks = _to_emasks(category)
        self.emasks &= ~emasks

        if not self.registered:
            pass ## 
        else:
            self.poller.modify(fd, self.emasks)

def get_channel_poller():
    return ChannelPoller.singleton()
    

import sys
import socket

from errcode import *

class Listenningable(object):
    socket = None

    def __init__(self, binding_addr):

        print "binding_addr: ", binding_addr
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.setblocking(False)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.bind(binding_addr)
        self.socket.listen(10)

    def get_socket(self):
        return self.socket

    def send(self):
        pass

    def recv(self):
        pass

    def close(self):
        self.socket.close()


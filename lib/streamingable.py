import sys
import socket
import Queue

from errcode import *

class Streamingable(object):
    socket = None
    msg_q  = None

    def __init__(self, mode, params):
        self.msg_q = Queue.Queue()

        if mode == "active":
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.connect(params)
        else: # for passive
            self.socket, addr = params.accept()
        self.socket.setblocking(False)

    def get_socket(self):
        return self.socket

    def put_msg(self, data):
        if data:
            self.msg_q.put(data)

    def send(self):
        try:
            data = self.msg_q.get_nowait()
            sz = self.socket.send(data)
        except Queue.Empty:
            return ecode_empty_queue
        except socket.error:
            return ecode_socket_error
        except socket.timeout:
            return ecode_socket_timeout
        except:
            return ecode_unknown_error
        else:
            if sz < len(data):
                return ecode_try_again
            else:
                return ecode_ok
    def recv(self):
        try:
            data = self.socket.recv(1024)
        except socket.error:
            return (ecode_socket_error, None)
        except socket.timeout:
            return (ecode_socket_timeout, None)
        except:
            return (ecode_unkown_error, None)
        else:
            if not data:
                return (ecode_ok, None)
            else:
                return (ecode_ok, data)

    def close(self):
        self.socket.close()



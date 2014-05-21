import sys
import socket
import struct
import fcntl

from liblogger import Log

singleton_relayconfig_object = None
singleton_proxyconfig_object = None

def get_ip_addr():
    ifname = 'eth0'
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    return socket.inet_ntoa(fcntl.ioctl(
                    s.fileno(),
                    0x8915, #socket.SIOCGIFADDR,
                    struct.pack('256s', ifname[:15])
                )[20:24])

def assign(key, val):
    key = val

class RelayConfig(object):
    logger = None

    _relay_server_host = "0.0.0.0"
    _relay_server_port = 20145
    _max_client_connections = 5
    _max_peer_connections_per_client = 10

    def __init__(self):
        self.logger = Log("RelayConfig")

    def relay_server_addr(self):
        if self._relay_server_host == "0.0.0.0":
            self._relay_server_host = get_ip_addr()
        return (self._relay_server_host, self._relay_server_port)

    def max_client_connections(self):
        if self._max_client_connections < 0:
            self._max_client_connections = 5
        return self._max_client_connections

    def max_peer_connections_per_client(self):
        if self._max_peer_connections_per_client < 0:
            self._max_peer_connections_per_client = 5
        return self._max_peer_connections_per_client

    def load(self, config_file="./relay.config"):
        try:
            fd = open(config_file)
            for line in fd:
                item = line.strip()
                if '=' not in item:
                    self.logger.log("unsupported format(withou =)")
                    return False

                key, val = item.split('=') 
                key, val = key.strip(), val.strip()

                if   key == "relay_server_host":
                    self._relay_server_host = val
                elif key == "relay_server_port":
                    self._relay_server_port = int(val)
                elif key == "max_client_connections":
                    self._max_client_connections = int(val)
                elif key == "max_peer_connections_per_client":
                    self._max_peer_connections_per_client = int(val)
                else:
                    self.logger.log("unsupported configure item(%s)"%key)
                    return False

            return True

        except IOError:
            self.logger.log("The config file(%s) not existed"%(config_file))
            return False

    @staticmethod
    def init_singleton(config_file):
        global singleton_relayconfig_object
        if not singleton_relayconfig_object:
            inst = RelayConfig()
            if inst.load(config_file):
                singleton_relayconfig_object = inst
        return singleton_relayconfig_object
    
    @staticmethod
    def singleton():
        return singleton_relayconfig_object
    
   
class ProxyConfig(object):
    logger = None

    _relay_server_host  = None
    _relay_server_port  = 20145
    _relay_service_port = 20148
    _remote_client_host = None
    _remote_client_port = None

    def __init__(self):
        self.logger = Log("RelayConfig")

    def relay_server_addr(self):
        return (self._relay_server_host, self._relay_server_port)

    def relay_service_addr(self):
        return (self._relay_server_host, self._relay_service_port)

    def remote_client_addr(self):
        return (self._remote_client_host,self._remote_client_port)
    
    def load(self, config_file):
        try:
            fd = open(config_file)
            for line in fd:
                item = line.strip()
                if not item:
                    continue
                if '=' not in item:
                    self.logger.log("unsupported format(%s)"%item)
                    return False 

                key, val = item.split('=')
                key, val = key.strip(), val.strip()
                if   key == "relay_server_host":
                    self._relay_server_host = val
                elif key == "relay_server_port":
                    self._relay_server_port = int(val)
                elif key == "relay_service_port":
                    self._relay_service_port = int(val)
                elif key == "remote_client_host":
                    self._remote_client_host = val
                elif key == "remote_client_port":
                    self._remote_client_port = int(val)
                else:
                    self.logger.log("[load] unsupported item(%s)"%key)
                    return False

            if not self._relay_server_host:
                self.logger.log("[load] relay server host is null")
                return False
            if not self._remote_client_host or not self._remote_client_port:
                return False
            return True

        except IOError:
            self.logger.log("The config file(%s) not existed"%(config_file))
            return False

    @staticmethod
    def init_singleton(config_file):
        global singleton_proxyconfig_object
        if not singleton_proxyconfig_object:
            inst = ProxyConfig()
            if inst.load(config_file):
                singleton_proxyconfig_object = inst
        return singleton_proxyconfig_object

    @staticmethod
    def singleton():
        return singleton_proxyconfig_object 

def get_proxyed_config():
    return ProxyConfig.singleton()

def get_relayed_config():
    return RelayConfig.singleton()


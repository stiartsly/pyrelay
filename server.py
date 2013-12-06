import sys
import socket
import fcntl
import struct


def get_ip_address():
    ifname = 'eth0'
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    return socket.inet_ntoa(fcntl.ioctl(
                s.fileno(),
                0x8915, #socket.SIOCGIFADDR,
                struct.pack('256s', ifname[:15])
            )[20:24])

if len(sys.argv) != 2:
    print "python server.py port"
    exit(-1)

s = socket.socket()

host = get_ip_address()
port = int(sys.argv[1])
print "port: ", port
s.bind((host,port))

s.listen(10)
while True:
    c,addr = s.accept()
    print "Got connection from ", addr
    print "[sever] received msg: ", c.recv(1024)
    c.send("response msg from server")
    c.close() 

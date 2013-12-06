import sys
import socket
import time

if len(sys.argv) != 2:
    print "python client.py host:port"

s =socket.socket()

#host = "192.168.4.125"
host = sys.argv[1].split(':')[0]
#port = 30005
port = int(sys.argv[1].split(':')[1])

print "host:", host
print "port:", port

s.connect((host, port))
s.send("###the client send the message")
print "[client] received msg: ", s.recv(1024)
s.close()

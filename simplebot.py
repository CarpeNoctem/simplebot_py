# Very simple irc bot in Python
# Bookmarks any links it sees into a text file in the same directory
# Author: https://github.com/CarpeNoctem
# Created (hastily) late 2012
# Last updated April 2014

# You probably want to edit the configuration settings at the bottom of this file..

import pickle, socket, ssl, threading, re
from time import sleep, time

# Here's our thread:
# This thread actually has too much stuff in it. For a connection thread, it really should only hold a connection loop,
# and die when disconnected. The rest should be in a bot thread (possibly the main thread), 
# under which a connection thread can be run
class ConnectionThread ( threading.Thread ):

    def __init__(self, config):
        self.config = config
        try:
            self.stats = pickle.load(open("stats.pickle")) #stats for number of pasted links
            print "Previous stats loaded."
        except IOError,EOFError:
            self.stats = {}
        self.running = 0
        self.reconnect = 1
        self.reconnect_wait = 3
        self.incomplete_line = ""
        threading.Thread.__init__ ( self )
    #/__init__()

    def run (self):
        while self.reconnect:
            self.connect()
            print "Waiting %s seconds before reconnecting..." % (self.reconnect_wait)
            sleep(self.reconnect_wait)
            self.reconnect_wait = self.reconnect_wait * 2
        return
    #/run
    
    def connect(self):
        if self.running > 0:
            return
        # Connect to the server:
        self.running = 1
        self.reconnect = 0
        self.client = ssl.wrap_socket(socket.socket( socket.AF_INET, socket.SOCK_STREAM ))
        self.client.connect( (self.config['server'], 6697) )
        sleep(1)
        self.register()
        self.client.settimeout(1)
        while self.running:
            if self.running < 1: break
            try:
                data = self.client.recv(4096)
                timeout_count = 0
                self.reconnect_wait = 3
            except:
                timeout_count += 1
                if timeout_count == 360: #ping the server if we haven't received anything in 3 minutes
                    print self.sendraw("PING %s" % (time()))
                if timeout_count == 400: #we probably lost connection at this point...
                    print "Connection dropped?"
                    self.running = 0
                continue
            if not data: break
            data = self.incomplete_line + data
            self.incomplete_line = ""
            lines = data.split("\r\n")
            if data.endswith("\r\n") != True:
                self.incomplete_line = lines.pop()
            for line in lines:
                self.parse(line)
        #/while
        if timeout_count > 360:
            self.reconnect = 1
        self.stop()
    #/connect
    
    def parse(self, data):
            try:
                info, args = data.rstrip("\r\n").lstrip(':').split(':',1)
                info = info.rstrip()
                print "{%s}[%s]" % (info,args)
                m = re.search("^(.+)!(.+)@(.+) (.+) (.+)$",info)
                if m and len(m.groups()) == 5:
                    nick, username, userhost, msgtype, replychan = m.groups()
                    if replychan == self.config['nick']:
                        replychan = nick
                else:
                    nick = username = userhost = msgtype = replychan = '' #should make this better later...
            except:
                nick = username = userhost = msgtype = replychan = '' #should make this better later...
                info = data.rstrip("\r\n").lstrip(':')
                args = ""
                if info != "":
                    print "!!%s!!" % (info)
            if 'PING' in info:
                self.pong(args)
            if '375' in info:
                self.cjoin(self.config['channel'])
            #commands for master
            if info.find(self.config['master']) == 0:
                if 'INVITE' in info:
                    print "joining ", args
                    self.cjoin(args)
                cmd = args
                if ' ' in cmd:
                    cmd, cmd_args = args.split(' ',1)
                if cmd == 'quityou':
                    self.reconnect = 0
                    self.stop()
                    return
                if cmd == 'ignore':
                    self.add_ignore(cmd_args.split(' '))
            if args == "!stats":
                self.privmsg(replychan,self.stats)
            link_detected = self.loglinks(args)
            if link_detected:
                if link_detected == 'repost':
                    self.privmsg(replychan,"(Repost)")
                else:
                    if nick not in self.stats:
                        self.stats[nick] = 0
                    self.stats[nick] += 1
                    self.persist_stats()
    #/parse
    
    def register(self):
        #self.sendraw("PASS none\r\n")
        self.sendraw("NICK %s" % (self.config['nick']))
        self.sendraw("USER %s %s %s :I'm a bot. My master is %s" % (self.config['nick'],self.config['rdns'],self.config['server'],self.config['master']))
    #/register
    
    def pong(self,pingstring):
        self.sendraw("PONG %s" % (pingstring))
    #/pong

    def cjoin(self,channel,pwd=""):
        if pwd != "":
            channel = channel + " " + pwd
        self.sendraw("JOIN %s" % (channel))
    #/cjoin

    def privmsg(self,channel,message=""):
        self.sendraw("PRIVMSG %s :%s" % (channel, message))
        print ">>PRIVMSG %s :%s" % (channel, message)
    #/privmsg

    def stop(self):
        if self.running >= 1:
            self.sendraw("QUIT :byebye")
            self.running = 0
            self.client.close()
            self.persist_stats()
            print "Bot stopped."
    #/stop
    
    def loglinks(self,test):
        if 'http' in test or 'ftp://' in test or 'spotify:' in test:
            #stop logging invalid links
            url_pat = '(((https?|ftp):\/\/)|www\.)(([0-9]+\.[0-9]+\.[0-9]+\.[0-9]+)|localhost|([a-zA-Z0-9\-]+\.)*[a-zA-Z0-9\-]+\.(com|net|org|info|biz|gov|name|edu|[a-zA-Z][a-zA-Z]))(:[0-9]+)?((\/|\?)[^ "]*[^ ,;\.:">)])?'
            m = re.search(url_pat, test, re.I)
            #adding spotify link pattern for silly people. :P
            if m is None:
                spot_pat = 'spotify:[a-zA-Z]+:[a-zA-Z0-9]+'
                m = re.search(spot_pat, test, re.I)

            if m is not None:
                #special code for a special someone...
                if any(term in test for term in self.config['links_ignorelist']):
                    return False
                #/special code
                filename = self.config['linksfile']
                try:
                    with open(filename,'r') as f:
                        existing_links = f.read()
                    if m.group().replace('https://','').replace('http://','') in existing_links:
                        return "repost"
                    else:
                        self.log(test,filename)
                        return True
                except Exception:
                    print "Problem reading file %s..." % (filename)
            else:
                #Stop here. Not a link.
                return False
        return False
    #/loglinks

    def add_ignore(self,terms):
        self.config['links_ignorelist'] = list(set(self.config['links_ignorelist'] + terms))
    #/add_ignore

    def persist_stats(self):
        print "Saving stats..."
        try:
            pickle.dump(self.stats,open("stats.pickle","w")) #stats for number of pasted links
        except IOError:
            print "...failed to write file"
    #/persist_stats

    def log(self,content,filename):
        try:
            f = open(filename,'a')
            f.write(content + "\n")
            f.close()
        except Exception:
            print "Problem logging to file %s..." % (filename)
    #/log

    def sendraw(self,contents):
        if self.running >= 1:
            try:
                self.client.send("%s\r\n" % (contents))
                return contents                
            except socket.error, e:
                self.reconnect = 1
                return "Socket error on write (Disconnected/timed-out?): %s" % (e)
    #/sendraw

    def is_running(self):
        return self.running
    #/is_running

#/ConnectionThread


#kick things off
print "here we go."
conf = {}
conf['server'] = 'irc.freenode.net'
from random import sample # remove this when you give your bot a static name
conf['nick'] = 'simplebot_' + str.join( "", sample("qwertyuiopasdfghjklzxcvbnm1234567890",4) )
conf['channel'] = '#bots'
conf['master'] = 'you'
conf['rdns'] = 'somewhere'
conf['linksfile'] = 'bookmarked_links.txt'
conf['logfile'] = conf['nick'] + '.log'
conf['links_ignorelist'] = [] # links you don't want to bookmark, Ex: ['furbies','cia.gov']

a = ConnectionThread(conf)
a.start()


while True:
    inpt = raw_input('--> ')
    if inpt == 'quit': break
    else:
        a.sendraw(inpt) #do you speak irc?
a.stop()

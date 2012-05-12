# -*- coding: utf8 -*-

from httplib import HTTPConnection 
from HTMLParser import HTMLParser
from xml.dom.minidom import parseString

import re, json, datetime, os, sys, time
from xml.etree.ElementTree import ElementTree
from StringIO import StringIO

from multiprocessing import Process, current_process, freeze_support
from BaseHTTPServer import HTTPServer
from SimpleHTTPServer import SimpleHTTPRequestHandler

import sqlite3
import logging

def create_logger():
	_log = logging.getLogger('main')
	_log.setLevel(logging.DEBUG)
	ch = logging.StreamHandler()
	ch.setLevel(logging.DEBUG)
	formatter = logging.Formatter('[%(levelname)s] %(asctime)s: %(message)s')
	ch.setFormatter(formatter)
	_log.addHandler(ch)
	return _log

_log = create_logger()

def remove_html_tags(data):
	p = re.compile(r'(<th(.*)</th>| align=center|<(/?)(font|p|a|b)(.*?)>)')
	return p.sub('', data)
def date_from_str(s,format='%d. %m. %Y'):
	return datetime.date.fromtimestamp(time.mktime(time.strptime(s, format)))
def parse_date(s):
	return date_from_str(re.findall(r'<b>\w+ ([0-9. ]+?)</b>', s)[0])

con = sqlite3.connect('db.sqlite3')
_log.info("Created sqltile3 connection..")

# page = "spse-po.edupage.org/substitution/subst_students2012-05-11.htm"

class Substitution():
	def __init__(self,hour,date=None):
		self.hour = hour
		self.teacher = None
		self.lesson = None
		self.nlesson = None
		self.status = 0
		self.steacher = None
		self.room = None
		self.chroom = None
		self.notice = None
		self.date = date
	def parseLesson(self,name):
		if "->" in name:
			name = [ a.strip() for a in name.split('->') ]
			self.lesson = name[1]
			self.nlesson = name[0]
			self.status += 1
		else:
			self.lesson = name
	def parseStatus(self,t):
		if t is None:
			# self.status += 0
			return
		if 'odpadlo' in t:
			self.status += 10
		else:
			self.status += 20
			self.steacher = t
	def parseRoom(self,name):
		if name is None:
			return
		if "->" in name:
			name = [ a.strip() for a in name.split('->') ]
			self.room = name[1]
			self.chroom = name[0]
			self.status += 100
		else:
			self.room = name

class Classroom():
	def __init__(self,name):
		self.name = name
		self.list = []
	def addSubst(self,hour,date=None):
		self.list.append( Substitution(hour,date) )
	def getLastSubst(self):
		return self.list[-1]

class Page():
	def __init__(self,table,teachers,date):
		self.table = table
		self.teachers = teachers
		self.date = date

class PageConn():
	def __init__(self):
		self.web_conn = HTTPConnection("spse-po.edupage.org")
		self.last_update = datetime.datetime.now()
		_log.debug("PageConn created..")
	def fetch(self):
		return
	def get(self):
		self.last_update = datetime.datetime.now()
		self.web_conn.request("GET", "/substitution/")
		a = self.web_conn.getresponse().read()
		return self.parse(a)
	def parse_teachers(self,s):
		s = str(remove_html_tags(s)).decode('utf-8')
		s = re.sub(r'\([^)]*\)', '', s)
		s = s.split(', ')
		s.reverse()
		ret = []
		c = 0
		while c < len(s):
			ret.append( s[c]+' '+s[c+1] )
			c += 2
		return ret
	def parse(self, content):
		if content is None:
			return
		_log.debug('PageConn: parse()')
		line = [ l.strip("\n\r\t") for l in content.splitlines() ]
		date = None
		teachers = None
		n = ''
		l = 0
		s = 0
		for i in range(len(line)):
			if "id='subst_div2'>" in line[i]:
				l = i
				s = 1
			if s == 1 and '<th align="center">' in line[i]:
				if 'Suplovanie' in line[i+1]:
					date = parse_date(line[i+1])
			if s == 1 and '<b>Informácie' in line[i]:
				if "<p align='center'><font size='2'><br><font size='2'><b>" in line[i+2]:
					teachers = self.parse_teachers(line[i+2])
			if s == 1 and '<tr class="row' in line[i]:
				s = 2
			if s == 2 and '</table>' in line[i]:
				break
			if s == 2:
				n += line[i] + "\n"
		n = "<html><body><table>" + remove_html_tags(n) + "</table></body></html>"
		return Page(n, teachers, date)

pageWorker = PageConn()

class SubstitutionData():
	def __init__(self):
		self.classrooms = []
		self.datetime = datetime.datetime.now()
		self.teachers = []		


class SubstitutionManager():
	def __init__(self):
		self.data = SubstitutionData()
		self.datetime = None
	def get(self,page):
		if not isinstance(page, Page):
			_log.error('somethings wrong')
			return
		tree = ElementTree()
		tree.parse(StringIO(page.table))
		classrooms = self.data.classrooms
		self.data.teachers.append({ page.date.isoformat(): page.teachers })
		self.datetime = datetime.datetime.now()
		current = None
		l = 0
		next = 0
		trs = list(tree.iter('tr'))
		for a in range(len(trs)):
			tds = list(trs[a].iter('td'))
			if next > 0:
				next -= 1
			for b in range(len(tds)):
				if b == 0 and next == 0:
					next = int(tds[b].attrib['rowspan'])
					l = a
					current = Classroom(tds[b].text.split(', '))
					classrooms.append( current )
					continue
				if b == 1 and l == a or b == 0 and l != a:
					current.addSubst(int(tds[b].text), page.date)
					continue
				if b == 2 and l == a or b == 1 and l != a:
					current.getLastSubst().teacher = tds[b].text
				if b == 3 and l == a or b == 2 and l != a:
					current.getLastSubst().parseLesson(tds[b].text) # here can be a change ->
				if b == 4 and l == a or b == 3 and l != a:
					current.getLastSubst().parseStatus(tds[b].text)
				if b == 5 and l == a or b == 4 and l != a:
					current.getLastSubst().parseRoom(tds[b].text)
				if b == 6 and l == a or b == 5 and l != a:
					current.getLastSubst().notice = tds[b].text


manager = SubstitutionManager()
manager.get( pageWorker.get() )

class ClassroomEncoder(json.JSONEncoder):
	def default(self,obj):
		if isinstance (obj, Classroom):
			return { 'classes': obj.name, 'substitutions': obj.list }
		if isinstance (obj, Substitution):
			return {
				'date': obj.date.isoformat(),
				'hour': obj.hour, 'teacher': obj.teacher, 'lesson': obj.lesson,
				'status': format(obj.status, "03d"), 'room': obj.room, 'chroom': obj.chroom,
				'notice': obj.notice, 'nlesson': obj.nlesson, 'steacher': obj.steacher
			}
		if isinstance (obj, SubstitutionManager):
			return {
				'created': obj.datetime.isoformat(), 'classrooms': obj.data.classrooms, 'version': '0.0.1b',
				'author': 'janmochnak@gmail.com', 'teachers': obj.data.teachers
			}
		return json.JSONEncoder.default(obj)

def json_encode(obj):
	return json.dumps(obj, cls=ClassroomEncoder, indent=4, sort_keys=True, ensure_ascii=False)

class RequestHandler(SimpleHTTPRequestHandler):
	def log_message(self, format, *args):
		_log.debug('[HTTP] '+format, *args)
	def do_GET(self):
		f = StringIO()
		f.write( json_encode(manager) )
		self.send_response(200)
		self.send_header("Content-type", "application/json; charset=utf-8")
		#self.send_header("Content-Length", str(f.tell()))
		self.end_headers()
		f.seek(0)
		if f:
			self.wfile.write( f.read().encode('utf-8') )
			f.close()

def serve_forever(server):
	try:
		server.serve_forever()
	except KeyboardInterrupt:
		pass

def runpool(address, number_of_processes):
	_log.info("Starting http server on http://%s:%d" % address)
	server = HTTPServer(address, RequestHandler)
	for i in range(number_of_processes):
		Process(target=serve_forever, args=(server,)).start()
	#serve_forever(server)

def run_server():
	www_root = os.path.dirname(__file__)
	addr = ('localhost', 8934)

	os.chdir(www_root)
	runpool(addr, 3)

if __name__ == '__main__':
	freeze_support()
	run_server()

# -*- coding: utf8 -*-
# python3

from http.client import HTTPConnection 
from html.parser import HTMLParser
from xml.dom.minidom import parseString

import re, json, datetime, os, sys, time
from xml.etree.ElementTree import ElementTree
from io import StringIO

from multiprocessing import Process, current_process, freeze_support
from http.server import HTTPServer
from http.server import SimpleHTTPRequestHandler

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
	def __init__(self,classes):
		self.hour = 0
		self.teacher = None
		self.lesson = None
		self.nlesson = None
		self.status = 0
		self.steacher = None
		self.room = None
		self.chroom = None
		self.notice = None
		self.date = None
		self.classes = classes
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
		_log.debug("PageConn: get http")
		self.web_conn.request("GET", "/substitution/")
		a = self.web_conn.getresponse().read()
		if not a is None:
			_log.debug('PageConn: recv data..')
			self.last_update = datetime.datetime.now()
			return self.parse(a)
	def parse_teachers(self,s):
		s = remove_html_tags(s)
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
		line = [ u.strip("\n\r\t") for u in str(content, encoding='utf-8').splitlines() ]
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
		_log.debug("PageConn: parsing done")
		return Page(n, teachers, date)

pageWorker = PageConn()

class SubstitutionData():
	def __init__(self):
		self.substitutions = []
		self.datetime = datetime.datetime.now()
		self.teachers = []

class SubstitutionManager():
	def __init__(self,pw):
		self.data = SubstitutionData()
		self.datetime = None
		self.pageWorker = pw
	def get(self):
		page = self.pageWorker.get()
		if not isinstance(page, Page):
			_log.error('somethings wrong')
			return
		tree = ElementTree()
		tree.parse(StringIO(page.table))
		substitutions = self.data.substitutions
		self.data.teachers.append({ page.date.isoformat(): page.teachers })
		self.data.datetime = datetime.datetime.now()
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
					current = Substitution(tds[b].text.split(', '))
					substitutions.append( current )
					continue
				if b == 1 and l == a or b == 0 and l != a:
					current.hour = int(tds[b].text)
					current.date = page.date
					continue
				if b == 2 and l == a or b == 1 and l != a:
					current.teacher = tds[b].text
				if b == 3 and l == a or b == 2 and l != a:
					current.parseLesson(tds[b].text) # here can be a change ->
				if b == 4 and l == a or b == 3 and l != a:
					current.parseStatus(tds[b].text)
				if b == 5 and l == a or b == 4 and l != a:
					current.parseRoom(tds[b].text)
				if b == 6 and l == a or b == 5 and l != a:
					current.notice = tds[b].text
		return self.data

manager = SubstitutionManager(pageWorker)

class ClassroomEncoder(json.JSONEncoder):
	def default(self,obj):
		if isinstance (obj, Substitution):
			return {
				'date': obj.date.isoformat(), 'classes': obj.classes,
				'hour': obj.hour, 'teacher': obj.teacher, 'lesson': obj.lesson,
				'status': format(obj.status, "03d"), 'room': obj.room, 'chroom': obj.chroom,
				'notice': obj.notice, 'nlesson': obj.nlesson, 'steacher': obj.steacher
			}
		if isinstance (obj, SubstitutionData):
			return {
				'created': obj.datetime.isoformat(), 'substitutions': obj.substitutions, 'version': '0.0.2',
				'author': 'janmochnak@gmail.com', 'teachers': obj.teachers
			}
		return json.JSONEncoder.default(obj)

def json_encode(obj,f):
	return json.dump(obj,f, cls=ClassroomEncoder, indent=2, sort_keys=True, ensure_ascii=False)

data = manager.get()

class RequestHandler(SimpleHTTPRequestHandler):
	def log_message(self, format, *args):
		_log.debug('[HTTP] '+format, *args)
	def do_GET(self):
		f = StringIO()		
		json_encode( data , f )
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

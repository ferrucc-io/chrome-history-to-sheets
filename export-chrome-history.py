#!/usr/bin/env python

# export-chrome-history
# 
# A script to upload your Google Chrome's history to a Google Sheet
#
#


from __future__ import print_function

from dotenv import load_dotenv

import argparse
from os import environ
from os.path import expanduser, join
from platform import system
from shutil import copy, rmtree
import sqlite3
from sys import argv, stderr
from tempfile import mkdtemp
from urllib.parse import urlparse
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import os

from pytz import utc
from apscheduler.schedulers.blocking import BlockingScheduler




load_dotenv()
SHEET = os.getenv("SHEET")
CREDENTIALS = os.getenv("CREDENTIALS")


script_version = "0.1"

html_escape_table = {
	"&": "&amp;",
	'"': "&quot;",
	"'": "&#39;",
	">": "&gt;",
	"<": "&lt;",
	}

output_file_template = """{items}\n"""

scope = ['https://spreadsheets.google.com/feeds',
         'https://www.googleapis.com/auth/drive']

credentials = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS, scope)


def html_escape(text):
	return ''.join(html_escape_table.get(c,c) for c in text)

def sanitize(string):
	res = ''
	string = html_escape(string)
	string = string.replace(",", "，")
	for i in range(len(string)):
		if ord(string[i]) > 127:
			res += '&#x{:x};'.format(ord(string[i]))
		else:
			res += string[i]

	return res


# Parse the command-line arguments

parser = argparse.ArgumentParser(formatter_class=argparse.RawDescriptionHelpFormatter,
		description="Convert Google Chrome's history file to a CSV.",
		epilog="(c) 2018 Ferruccio Balestreri\nhttps://ferrucc.io")
parser.add_argument("input_file", nargs="?",
		help="The location of the Chrome history file to read. If this is omitted then the script will look for the file in Chrome's default location.")
parser.add_argument("-v", "--version", action="version",
		version="export-chrome-history {}".format(script_version))

args = parser.parse_args()

sched = BlockingScheduler({
    'apscheduler.jobstores.default': {
        'type': 'sqlalchemy',
        'url': 'sqlite:///jobs.sqlite'
    },
    'apscheduler.executors.default': {
        'class': 'apscheduler.executors.pool:ThreadPoolExecutor',
        'max_workers': '20'
    },
    'apscheduler.executors.processpool': {
        'type': 'processpool',
        'max_workers': '5'
    },
    'apscheduler.job_defaults.coalesce': 'false',
    'apscheduler.job_defaults.max_instances': '3',
    'apscheduler.timezone': 'UTC',
})

def script():
	# Determine where the input file is

	if args.input_file:
		input_filename = args.input_file
	else:
		if system() == "Darwin":
			input_filename = expanduser("~/Library/Application Support/Google/Chrome/Default/History")
		elif system() == "Linux":
			input_filename = expanduser("~/.config/google-chrome/Default/History")
		elif system() == "Windows":
			input_filename = environ["LOCALAPPDATA"] + r"\Google\Chrome\User Data\Default\History"
		else:
			print('Your system ("{}") is not recognized. Please specify the input file manually.'.format(system()))
			exit(1)

		try:
			input_file = open(input_filename, 'r')
		except IOError as e:
			if e.errno == 2:
				print("The history file could not be found in its default location ({}). ".format(e.filename) +
						"Please specify the input file manually.")
				exit(1)
		else:
			input_file.close()

	# Make a copy of the database, open it, process its contents, and write the
	# output file

	temp_dir = mkdtemp(prefix='export-chrome-history-')
	copied_file = join(temp_dir, 'History')
	copy(input_filename, copied_file)

	try:
		connection = sqlite3.connect(copied_file)
	except sqlite3.OperationalError:
		# This error message is a *little* misleading, since the problem actually
		# occurred when we tried to open copied_file, but chances are that if we got
		# to this point then the problem lies with the file itself (e.g. it isn't a
		# valid SQLite database), not with our ability to read the file.
		print('The file "{}" could not be opened for reading.'.format(input_filename))
		rmtree(temp_dir)
		exit(1)

	
	urls = connection.cursor()

	try:
		urls.execute("SELECT url, title FROM urls")
	except sqlite3.OperationalError:
		print('There was an error reading data from the file "{}".'.format(args.input_file))
		rmtree(temp_dir)
		exit(1)

	items = "Title, Address\n"
	for row in urls:
		if len(row[1]) > 0:
			parsed_uri = urlparse(row[0])
			sanitizedLink = '{uri.scheme}://{uri.netloc}/'.format(uri=parsed_uri)
			sanitizedTitle = sanitize(row[1])
			items += "\"" + sanitizedTitle  + "\"" + " , \"" + sanitizedLink  + "\""  + "\n"

	connection.close()
	rmtree(temp_dir)

	output_file = open("history.csv","w+")

	output_file.write(output_file_template.format(items=items))
	output_file.close()


	# Google Sheet Importing happens here
	print("Updating history")
	gc = gspread.authorize(credentials)
	content = open('history.csv', 'r').read()

	gc.import_csv(SHEET, content)

	os.remove("history.csv")

script()
sched.add_job(script, 'interval', hours=1)
sched.start()
print("Shutting down")
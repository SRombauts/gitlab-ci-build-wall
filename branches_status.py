#!/usr/bin/env python
# -*- coding: utf-8 -*-
import cgi			# CGI
import cgitb		# CGI - debug exception handler
import urlparse
from datetime import datetime
import os
import sys
import fcntl
import json
import PyJSONSerialization
import traceback

SCRIPT_VERSION       = "v1.3"
BRANCHES_STATUS_JSON = "branches_status.json" # JSON status of branches
BRANCHES_STATUS_LOCK = "branches_status.lock" # LOCK for the JSON file
MAX_BRANCH_PER_PAGE  = 11

CSS = '''
html { 
  height: 100%;
}

* {
  margin: 0;
  padding: 0;
  background-color: #000000;
  font-color: #FFFFFF;
  color: #FFFFFF;
}

#titre {
  font-size: 3.5em;
  font-family: "Arial", Arial, sans-serif;
  text-align: center;
}

#ctx_menu {
  visibility: hidden;
  position: absolute;
  display: inline;
  background: #554444;
}

table {
  margin: 5px 0 30px 0;
}

table tr th, table tr td {
  background: #554444;
  color: #FFF;
  border-radius: 8px;
  padding: 8px 2px;
  font-family: "Arial", Arial, sans-serif;
  text-align: center;
}

table tr th {
  font-size: 1.6em;
}

table tr td {
  background: #444444;
  font-size: 1.4em;
}

table .branch {
  font-size: 3em;
  text-align: left;
}

table .pipeline { 
  background: #444444;
  text-align: center;
}

table .pending { 
  background: #000000;
  text-align: center;
  padding: 4px 4px;
  border-radius: 6px;
}

table .created { 
  background: #000000;
  text-align: center;
  padding: 4px 4px;
  border-radius: 6px;
}

table .skipped { 
  background: #000000;
  text-align: center;
  padding: 4px 4px;
  border-radius: 6px;
}

table .running { 
  background: #444444;
  text-align: center;
  padding: 4px 4px;
  border-radius: 6px;
}

table .success { 
  background: #00BB00;
  text-align: center;
}

table .OK { 
  background: #00BB00;
  text-align: center;
}

table .failed {
  background: #DD0000;
  text-align: center;
}

a {
  text-decoration: none;
}'''

# activates a special exception handler that will display detailed reports in the Web browser if any errors occur
cgitb.enable()
sys.stderr = sys.stdout

def escape(txt):
	return cgi.escape(txt, True)

# Variant of a branch  - Allow to monitor different jobs 
# 1 variant = 1 column shown on the display
class VariantStatus:
	def __init__(self):
		self.build_id  = None
		self.status    = None # 'pending' 'created' 'skipped' 'running' 'success' 'failed' 'canceled' 'OK'
		self.previous  = None # 'success' 'failed' 'OK'
		self.url       = None

	@classmethod
	def create(cls, status, previous, url, build_id):
		retour = cls()
		retour.build_id   = build_id
		retour.status     = status
		retour.previous   = previous
		retour.url        = url
		return retour

# Status of a branch
class BranchStatus:
	def __init__(self):
		self.pipeline_id = 0
		self.url         = None
		self.variants    = dict()
		self.date_maj    = None

	def set_id(self, pipeline_id, url):
		self.pipeline_id = pipeline_id
		self.url         = url

	def set_result (self, variant, status, url, build_id):
		old_build_id = 0
		previous = None
		if self.variants.has_key(variant):
			old_build_id = self.variants[variant].build_id
			old_status   = self.variants[variant].status   # 'pending' 'created' 'skipped' 'running' 'canceled' 'success' 'failed' 'OK'
			old_previous = self.variants[variant].previous # 'success' 'failed' 'OK'
			# During a new build ("pending", "created", "skipped", "running" or "canceled"),
			if (status == "pending" or status == "created" or status == "skipped" or status == "running" or status == "canceled"):
				# if the old build status was a definitive result ("success", "failed" or "OK"), keep it as the "previous" result to display as background
				if (old_status == "success" or old_status == "failed" or old_status == "OK"):
					previous = self.variants[variant].status
				else: # Else, by default simply maintain any "previous" build status
					previous = old_previous
			# else, if it is a definitive status ("success", "failed" or "OK") remove the old status
		# Only keep information on the most recent build for the variant
		if build_id >= old_build_id:
			self.variants[variant] = VariantStatus.create(status, previous, url, build_id)
			self.date_maj = datetime.now().isoformat()

	def force_result (self, variant, status):
		if self.variants.has_key(variant):
			url      = self.variants[variant].url
			build_id = self.variants[variant].build_id
		else:
			url      = None
			build_id = 0
		self.set_result(variant, status, url, build_id)


# Cross process locking for the Json file
# http://blog.vmfarms.com/2011/03/cross-process-locking-and.html
class Lock:
	def __init__(self, filename):
		self.filename = filename
		self.handle = open(filename, 'w')
	
	# Bitwise OR fcntl.LOCK_NB if you need a non-blocking lock 
	def acquire(self):
		fcntl.flock(self.handle, fcntl.LOCK_EX)
	
	def release(self):
		fcntl.flock(self.handle, fcntl.LOCK_UN)
	
	def __del__(self):
		self.handle.close()


#########################################################################################################################
#
#          Main

try:
	lock = Lock(BRANCHES_STATUS_LOCK)
	lock.acquire()

	####################################
	# Load previous CI results from file
	try:
		with open(BRANCHES_STATUS_JSON, "r") as f:
			branch_list = PyJSONSerialization.load(f.read(), globals())
	except:
		branch_list = dict()

	save_to_file = False

	# Read parameters passed by the command line (CGI)
	try:
		get_params = urlparse.parse_qs(os.environ['QUERY_STRING'])
		force_branch  = get_params['branch'][0]
		force_variant = get_params['variant'][0]
		force_status  = get_params['force_status'][0]
		if force_branch and force_variant and force_status:
			branch_list[force_branch].force_result(force_variant, force_status)
			save_to_file = True
	except:
		pass

	# Read json data (if available) in the body of the request
	try:
	  #json_status = json.load(sys.stdin)
		raw_data = sys.stdin.read()

		json_status = json.loads(raw_data)

		if json_status["object_kind"] == "pipeline":
			pipeline_id = json_status["object_attributes"]["id"]
			branch      = json_status["object_attributes"]["ref"]
			status      = json_status["object_attributes"]["status"] # 'pending' 'running' 'success' 'failed' 'canceled'
			builds      = json_status["builds"]
			web_url     = json_status["project"]["web_url"]

			# Update CI results only if there is a new result provided by the Gitlab CI Pipeline Webhook
			if branch not in branch_list:
				update = True
				branch_list[branch] = BranchStatus()
			elif pipeline_id == branch_list[branch].pipeline_id:
				update = True
			elif pipeline_id > branch_list[branch].pipeline_id:
				update = True
			else:
				update = False

			if update:
				url = web_url + "/pipelines/" + str(pipeline_id)  
				branch_list[branch].set_id(pipeline_id, url)
				save_to_file = True

				for build in builds:
					variant   = build["name"]
					status    = build["status"]
					build_id  = build["id"]
					url       = web_url + "/builds/" + str(build_id)  
					branch_list[branch].set_result(variant, status, url, build_id)

		elif json_status["object_kind"] == "build":
			branch   = json_status["ref"]
			variant  = json_status["build_name"]
			build_id = json_status["build_id"]
			status   = json_status["build_status"]
			web_url  = json_status["repository"]["homepage"]
			url      = web_url + "/builds/" + str(build_id)  

			if branch in branch_list:
				if variant in branch_list[branch].variants:
					if build_id == branch_list[branch].variants[variant].build_id:
						if status != branch_list[branch].variants[variant].status:
							branch_list[branch].set_result(variant, status, url, build_id)
							save_to_file = True

					elif build_id > branch_list[branch].variants[variant].build_id:
						branch_list[branch].set_result(variant, status, url, build_id)
						save_to_file = True

	except ValueError as exception:
		# no data, this is not a Gitlab request
		pass
	except Exception as exception:
		pass


	####################################
	# Save new results to file
	if save_to_file:
		# TODO : limit number of branches to store in the json file (drop oldest ones by timestamp)
		with open(BRANCHES_STATUS_JSON, "w") as f:
			f.write (PyJSONSerialization.dump(branch_list))

finally: 
	lock.release()

# ###############################################################
# Display CI results
#
# Build a table showing :
# - Branch name
# - status of all the build variants of this branch

print '''Content-type: text/html; charset=utf-8'

<html>
<head>
  <title>Branch status</title>
  <meta http-equiv="refresh" content="20">
  <style>''' + CSS + '''</style>
</head>
<script language="javascript" type="text/javascript">
function ShowMenu(self, e) {
console.log(self.id)
  var posx = e.clientX + window.pageXOffset + 'px'; // Left Position of Mouse Pointer
  var posy = e.clientY + window.pageYOffset + 'px'; // Top Position of Mouse Pointer
  var menu = self.querySelectorAll("#ctx_menu")[0];
  menu.style.visibility = 'visible';
  menu.style.position = 'absolute';
  menu.style.display = 'inline';
  menu.style.left = posx;
  menu.style.top = posy;
  self.onmouseleave = function(){menu.style.visibility = 'hidden';};
  
  return false;
}
</script>
'''

# Iterate through branch list to extract the list of variants
variant_list = []
for branch_name, branch_status in branch_list.iteritems():
	for variant_name, variants in branch_status.variants.iteritems():
		if variant_name not in variant_list :
			variant_list.append(variant_name)

# Header of the table
print '''<div id="titre">Branch Status</div>'''
print '''<table>'''
print '''<tr><th/>'''
for variant in variant_list:
	variant_title = variant.split(":", 1)
	print '''<th class="titre">''' + variant_title[0] + "<br/>" + variant_title[-1] + '''</td>''' # extract "quick" and "linux" from "quick:linux"
print '''</tr>'''

# Iterate through branches sorted by date of the last update
cpt = 0
for (branch_name, branch_status) in sorted(branch_list.items(), key=lambda(k,v): v.date_maj, reverse=True):
	if branch_status.url:
		print '''<tr><td class="branch"><a class="pipeline" href="'''+branch_status.url+'''">''' + branch_name + '''</a></td>'''
	else:
		print '''<tr><td class="branch">''' + branch_name + '''</a></td>'''

	# Add a column for each variant
	for variant in variant_list:
		try:
			status   = branch_status.variants[variant].status
			previous = branch_status.variants[variant].previous
			if not previous:
				previous = status
			url      = branch_status.variants[variant].url
			if url:
				href = ''' href="''' + url + '''"'''
			else:
				href = ""
			print '''<td class="''' + previous + '''" onContextMenu="return ShowMenu(this, event);">
			<div id="ctx_menu">
			<a href="?branch=''' + escape(branch_name) + '''&variant=''' + escape(variant) + '''&force_status=OK"/>Force OK</a>
			</div>
			<a class="''' + status + '''"''' + href + '''>''' + status.upper() + '''</a>
			</td>'''
		except KeyError:
			# The variant doesn't exists for this branch
			print '''<td/>'''

	print '''</tr>'''
	cpt += 1
	if cpt >= MAX_BRANCH_PER_PAGE:
		# Stop when whe reach the maximum number of branch to display
		break
	
print '''</table>
'''+SCRIPT_VERSION+'''
</html>'''

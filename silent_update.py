#!/usr/bin/env python3

"""
Copyright 2022 Buoy Health, Inc.

Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except in compliance with the License. You may obtain a copy of the License at http://www.apache.org/licenses/LICENSE-2.0.

Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the License for the specific language governing permissions and limitations under the License.
"""

"""
Source: https://github.com/t-lark/Auto-Update/
This script will silently patch any app by bundle ID, but only if the app itself is not running
you must supply the bundle ID of the app to check and the policy event manual trigger for jamf as
positional parameters 3 and 4

author:  tlark

Mac Admin Slack @tlark

"""

"""
Modifications by: Matt Hrono
MacAdmins: @matt_h
"""

# import modules
import sys
import subprocess

from Cocoa import NSRunningApplication

"""
global variables:
	4 - bundle ID of the app to check
		you may supply multiple bundle IDs by adding them comma separated as a parameter in jamf pro in the event a developer changes the bundle ID
	5 - jamf policy event trigger to install the app
"""
APPS = sys.argv[4].split(",")
POLICY = sys.argv[5]

# start functions
def check_if_running(bid):
	"""
	Use a native macOS API to determine whether or not the app is running using its bundle ID
	Return a boolean value based on the result
	"""
	app = NSRunningApplication.runningApplicationsWithBundleIdentifier_(bid)
	if app:
		return True
	if not app:
		return False


def run_update_policy(event):
	"""
	This function accepts event as a trigger for a jamf policy to install an app package, such as 'autoupdate-Slack'
	The jamf binary is called to explicitly run the policy with the specified event trigger
	If the event trigger is empty, do nothing
	"""
	cmd = ["/usr/local/bin/jamf", "policy", "-event", event]
	proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
	out, err = proc.communicate()
	if proc.returncode != 0:
		print("Error: %s" % err)


def main():
	"""
	For each bundle ID, check if it's running or not
	If running, exit silently
	Otherwise, call the update policy to update the app
	"""
	for app in APPS:
		if check_if_running(app):
			sys.exit(0)
	else:
		run_update_policy(POLICY)


# run the main
if __name__ == "__main__":
	main()
	
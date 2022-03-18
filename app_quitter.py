#!/usr/bin/env python3

"""
Copyright 2022 Buoy Health, Inc.

Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except in compliance with the License. You may obtain a copy of the License at http://www.apache.org/licenses/LICENSE-2.0.

Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the License for the specific language governing permissions and limitations under the License.
"""

"""
Source: https://github.com/t-lark/Auto-Update/

Heavily modified by: Matt Hrono - Buoy Health, Inc.
MacAdmins: @matt_h

This script will prompt end users to quit apps, or force quit apps depending on the options passed
in the positional parameters

Since this will be ran by jamf remember the first 3 parameters are reserved by jamf, so we will start with parameter 4

APPS will be a comma separated list of bundle IDs of apps you want this code to quit, example:

com.apple.Safari,org.mozilla.firefox,com.google.Chrome

PROMPT will be the parameter you use to decide to prompt the user or not, use strings "true" or "false"

APP_NAME will be the name of the application and how you want to present it in a dialog box, i.e. Safari or Safari.app

POLICY_EVENT is the jamf event to trigger the policy to update the app
This value can also be "false" which will skip the update function and not call any jamf policies

FORCE_QUIT is set to true or false in jamf as a positional parameter, if you set this to true it does as advertised
and will force quit the apps by bundle ID and force an update

SYMBOL is the unicode string for the heart emoji, because we can

MESSAGE is the actual message you wish to display to the end user

COMPLETE is the message that will pop when the patch is complete

FORCE_MSG = the template message to pop when doing a forced update for security reasons
"""

# import modules
import sys
import subprocess
import os
import time
import glob
import plistlib

from Cocoa import NSRunningApplication
from AppKit import NSWorkspace
from threading import Timer
from datetime import datetime, timedelta

"""
Input parameters from jamf:
	4  - list of bundle IDs
	5  - whether or not to prompt the user to quit the app--converts to boolean
	6  - display name of the application for user dialogs
	7  - jamf policy event trigger for the app installation
	8  - whether or not to force quit the app--converts to boolean
	9  - policy event trigger for an identical policy (running this script with the same parameters) to be called if the user elects to defer
	10 - number of times the user is allowed to defer the update
"""
APPS = sys.argv[4].split(",")
PROMPT = sys.argv[5].lower() == 'true'
APP_NAME = sys.argv[6]
POLICY_EVENT = sys.argv[7]
FORCE_QUIT = sys.argv[8].lower() == 'true'
DEFER_POLICY_EVENT = sys.argv[9]
DEFER_LIMIT = int(sys.argv[10]) or 14

## global variables
# IMPORTANT: insert your org name here
orgName = ''
# path to your org's icon (not required)
iconPath = '/path/to/your/icon.png'
# current date
date_today = datetime.date(datetime.now())
# blue heart emoji for user dialogs
SYMBOL = b'\xf0\x9f\x92\x99'
# message to prompt the user to quit and update an app
def defer_message(deferrals_used):
	"""
	Set the messaging to use for normal deferrable update prompts
	
	This prompt will be used as the description for jamfHelper when a user is bring prompted to update an app if deferrals are available
	"""
	global DEFER_MESSAGE
	DEFER_MESSAGE = """Hello!

{3} IT would like to patch {0}.  Please click on the "OK" button to continue--this will trigger the app to quit. Please save your work. We'll let you know when the update is finished.

If you'd prefer to update later, select a deferral time below, or defer now and use the {3} Self Service app to update at your convenience.

You may defer this update up to {2} more time(s).

{1} {3} IT

""".format(
	APP_NAME, SYMBOL.decode("utf-8"), deferrals_used, orgName
)

# message when deferrals have been exhausted
MESSAGE = """Hello!

{2} IT would like to patch {0}.  Please click on the "OK" button to continue--this will trigger the app to quit. Please save your work.

Deferral is not available. {0} will be closed and updated. We'll let you know when the update is finished.

{1} {2} IT

""".format(
	APP_NAME, SYMBOL.decode("utf-8"), orgName
)

# message to use when the update will be forced
FORCE_MSG = """Hello!

{2} IT would like to patch {0}.  This is an emergency patch and the application will be quit to deploy security patches.

{1} {2} IT

""".format(
	APP_NAME, SYMBOL.decode("utf-8"), orgName
)

# message to notify the user upon completion
COMPLETE = """Thank You!

{0} has been updated successfully.  Do you want to reopen it?

""".format(
	APP_NAME
)

# start functions

def load_plist(plist_path):
	# Load and return data from a plist
	with open(plist_path, 'rb') as plist:
		plist_data = plistlib.load(plist)
	
	return plist_data

def dump_plist(plist_data, plist_path):
	# Dump data into a plist
	with open(plist_path, 'wb') as plist:
		plistlib.dump(plist_data, plist)

def check_install_date():
	"""
	Read the plist containing information about when the app in question was last updated
	
	If the receipt doesn't exist, either it was deleted erroneously or this is the first time this app is being updated on this device
	Either way, this check can be skipped if the file isn't there to read
	If more than 120 days have passed since the last update, exhaust all deferrals and force the update now
	"""
	if not os.path.exists(receipt_file):
		return
		
	install_data = load_plist(receipt_file)

	last_install_date = datetime.strptime(install_data[POLICY_EVENT], '%Y-%m-%d').date()
	delta = date_today - last_install_date
	print(f"This app was last updated on {last_install_date}, which was {delta.days} days ago.")
	if delta.days > 120:
		print("More than 120 days have passed since the last update, forcing update now...")
		global DEFER_LIMIT
		DEFER_LIMIT = 0

def write_install_date():
	"""
	Write out a plist containing the current date to record when the app was updated
	
	This will be checked by check_install_date on future runs to enforce the SLA
	"""
	install_data = {
		POLICY_EVENT : str(date_today),
	}
	
	dump_plist(install_data, receipt_file)

# return bundle ID if the app is running
def get_app(bid):
	return next((a for a in NSRunningApplication.runningApplicationsWithBundleIdentifier_(bid)), None)

def check_if_running(bid):
	"""
	Use a native macOS API to determine whether or not the app is running using its bundle ID
	
	Return a boolean value based on the result
	"""
	app = get_app(bid)
	return bool(app)

def remove_daemons(policy_event):
	"""
	Clean up launchdaemons from previous runs of this script
	
	If the current iteration is running from a LaunchDaemon, that daemon will still be present after the script exists
	It will need to be unloaded and deleted before the script exits
	Otherwise, it will be loaded again next time the device restarts and the user will get an erroneous update prompt
	"""
	daemon_files = glob.glob("/Library/LaunchDaemons/com.appUpdates.policydefer.*.{}.plist".format(policy_event.replace(" ", "")))
	
	for daemon in daemon_files:
		try:
			os.remove(daemon)
		except Exception as e:
			print("Error deleting daemon: ", str(e))

def set_deferral(deferral_period, policy_event):
	"""
	Write out and load a LaunchDaemon to call the deferral policy after the user's selected time
	
	Need to make a fresh file for each deferral, because unloading the existing one kills the jamf process that's trying to make the new one
	Chicken and egg situation, but easily worked around by creating unique daemons using epoch time
	This function will delete all daemons for the app trying to update before creating the new one
	"""
	
	remove_daemons(POLICY_EVENT)
	
	daemon_time = int(time.time())
	daemon_label = "com.appUpdates.policydefer.{}.{}".format(daemon_time, policy_event.replace(" ", ""))
	daemon_file = "/Library/LaunchDaemons/{}.plist".format(daemon_label)

	cmd = [
		"/bin/launchctl",
		"load",
		"-w",
		daemon_file,
	]
	
	daemon_data = {
		"Label" : daemon_label,
		"LaunchOnlyOnce" : True,
		"ProgramArguments" : (
			"/usr/local/bin/jamf",
			"policy",
			"-event",
			DEFER_POLICY_EVENT,
		),
		"StartInterval" : int(deferral_period),
	}
	
	dump_plist(daemon_data, daemon_file)
	
	proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
	_, err = proc.communicate()
	
	if err:
		print("Error: %s" % err)
		
def check_deferral_count():
	"""
	Check how many deferrals have been used
	
	When generating the prompt to display to the user in the user_prompt function, we need to know whether or not the user will be permitted to defer the update
	user_prompt will call this function and expect a boolean value back
	First, check to see if the plist storing deferral information exists--if it doesn't, create it and set the number of used deferrals to 0
	Otherwise, read the plist to check how many deferrals have been used prior to this update attempt
	
	If the number of deferrals used is greater than or equal to the deferral limit, return False to user_prompt, which will cause it to not offer deferral options and force the update to install now
	The number of deferrals used could be greater than the limit if after some number of deferrals, the check_install_date function trips the 120-day SLA and sets DEFER_LIMIT to 0
	
	Finally, if deferrals are still available to be used, call defer_message to populate the deferral prompt with how many more deferrals the user has available and return True to user_prompt, which will cause it to add deferral options to the prompt
	"""
	print("Deferral limit is {}".format(DEFER_LIMIT))
	
	defer_path = "/Library/Application Support/{}".format(orgName)
	if not os.path.exists(defer_path):
		os.makedirs(defer_path)
	
	global defer_file
	defer_file = os.path.join(defer_path, "policydefer_{}.plist".format(POLICY_EVENT.replace(" ", "")))
	
	if not os.path.exists(defer_file):
		limit_value = {
			"limit" : DEFER_LIMIT,
			"used" : "0",
		}
		
		dump_plist(limit_value, defer_file)
		
	global defer_count

	defer_count = load_plist(defer_file)

	if int(defer_count['used']) >= int(DEFER_LIMIT):
		print("All deferrals used")
		return False
	else:
		print("{} deferrals have been used".format(defer_count['used']))
		defer_message(int(DEFER_LIMIT) - int(defer_count['used']))
		return True

def user_prompt(prompt=None, bid=None, reopen_app=False):
	"""
	Prompt the user to update an application
	
	Build the cmd to call jamfHelper
	Set the prompt to let the user know about their deferral options, and add options to the prompt if available
	If all deferrals have been used, change the prompt to offer no deferrals
	Use jamfHelper to generate a dialog for the user
	prompt takes in one of the messages defined at the top of this script
	If the update is complete and the user is being asked if they'd like to reopen the app, we make the default button OK for easy relaunch
	This prompt will also time out after 60 seconds and automatically reopen the app if they choose nothing
	Finally, if the user does want to reopen the app, determine the app path by bundle ID and open that app
	
	If the update is not being forced (either due to being flagged as a forced update or having no deferrals remaining), the exit code from jamfHelper is parsed to determine how the user would like to proceed
	This function returns True if the user opted to install the update now, which goes back to run() to proceed with quitting the app and calling the update
	Otherwise, this function returns False (after handling deferrals, if necessary), causing the script to exit without quitting the app or calling the update
	The boolean values returned from this function are only used if the user has a choice whether or not to install the update
	If the update is being forced, or the update is complete and the user is being asked if they want to re-launch the updated app, the return value from this function is not needed and ignored
	"""
	
	icon = iconPath
	if not os.path.exists(icon):
		icon = "/System/Library/CoreServices/Problem Reporter.app/Contents/Resources/ProblemReporter.icns"
		
	cmd = [
		"/Library/Application Support/JAMF/bin/jamfHelper.app/Contents/MacOS/jamfHelper",
		"-windowType",
		"utility",
		"-title",
		"Managed App Update",
		"-icon",
		icon,
		"-button1",
		"OK",
	]
	
	if reopen_app:
		cmd.extend(["-button2", "Cancel", "-defaultButton", "1", "-timeout", "60",])
	else:
		if check_deferral_count():
			prompt = DEFER_MESSAGE
			cmd.extend(["-showDelayOptions", '"0, 600, 1200, 3600, 10800, 86400, 172800"'])
		else:
			prompt = MESSAGE
			
	cmd.extend(["-description", prompt,])

	proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
	
	kill = lambda process: process.kill()	
	prompt_timer = Timer(300, kill, [proc])
	
	try:
		prompt_timer.start()
		out, err = proc.communicate()
	finally:
		prompt_timer.cancel()
	
	"""
	The remaining lines in this function parse the exit code returned from the jamfHelper process, which only returns 0 under specific circumstances.
	A nonzero exit code for jamfHelper does not indicate failure.
	If the user selected a deferral period and clicked button 1 to confirm deferral, the exit code will be the deferral period (in seconds) followed by 1 for button 1.
	For example, a 10 minute deferral would return 6001.
	To review the full list of jamfHelper exit codes and their functions, run '/Library/Application\ Support/JAMF/bin/jamfHelper.app/Contents/MacOS/jamfHelper -help' in a shell
	"""
	if err:
		print("Error: %s" % err)
		
	try:
		exit_code = int(out)
		button_selected = int(str(exit_code)[-1])
	except(ValueError, IndexError) as err:
		print("jamfHelper exit code could not be parsed: " + str(err))
		print("Deferring for one hour...")
		set_deferral(3600, POLICY_EVENT)
		return False
	
	deferral_seconds = int(out[:-1]) if len(out) > 1 else 0
	
	# Return True regardless of what the user does if the update is being forced
	if prompt == MESSAGE or FORCE_QUIT:
		return True
	
	if exit_code == 239 or not out:
		return False
		# to be implemented when jamf 10.23 is released to support auto-retry on failed policies
		# sys.exit(1)
	if button_selected == 1 and exit_code != 1 and not reopen_app:
		print("User elected to defer for " + str(deferral_seconds // 60) + " minutes")
		used_count = int(defer_count['used']) + 1
		counter = {
			"limit" : DEFER_LIMIT,
			"used" : used_count,
		}

		dump_plist(counter, defer_file)

		set_deferral(deferral_seconds, POLICY_EVENT)
		return False
	elif proc.returncode == 0:
		if reopen_app:
			print("Relaunching app...")
			appPath = NSWorkspace.sharedWorkspace().URLForApplicationWithBundleIdentifier_(bid).path()
			subprocess.call(
				["/usr/bin/open", "-a", appPath]
			)
		return True
	elif button_selected == 2 or proc.returncode == -9:
		return False
	else:
		return False
		
def quit_application(bid, force=False):
	"""
	Quit the application to be updated if the update isn't being deferred or otherwise skipped
	
	If the app should be force-terminated (in the case of a forced update), kill it immediately
	Otherwise, attempt to quit it gracefully
	This function will loop once per second for 30 seconds monitoring whether or not the app is still running
	If still running after 10 quit attempts, it switches to forced termination
	"""
	print('Terminating app {}'.format(bid))

	for i in range(30):
		app = get_app(bid)

		if not app or app.isTerminated():
			print('{} is not running.'.format(bid))
			break

		if force:
			app.forceTerminate()
		else:
			app.terminate()

		if i >= 10 and not app.isTerminated():
			print('Terminating {} taking too long. Forcing terminate.'.format(bid))
			app.forceTerminate()

		print('Waiting on {} to terminate'.format(bid))
		time.sleep(1)

def run_update_policy(event):
	"""
	Call the jamf policy to install the updated app package
	
	This function accepts event as a trigger for a jamf policy to install an app package, such as 'autoupdate-Slack'
	The jamf binary is called to explicitly run the policy with the specified event trigger
	If the event trigger is empty, do nothing
	"""
	if not event:
		return
	defer_counter_file = "/Library/Application Support/appUpdates/policydefer_{}.plist".format(POLICY_EVENT.replace(" ", ""))
	if os.path.exists(defer_counter_file):
		print("Removing deferral counter file...")
		os.remove(defer_counter_file)
	print("Calling jamf policy...")
	cmd = ["/usr/local/bin/jamf", "policy", "-event", event]
	proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
	_, err = proc.communicate()
	write_install_date()
	if proc.returncode:
		print("Error: %s" % err)

def check_for_zoom():
	"""
	Check to see if the user is on an active Zoom call by looking for the CptHost process
	
	This is done to ensure we don't interrupt an active call with an update prompt
	Loop every 30 seconds for up to 5 minutes in case a call is about to end and we can catch them right after
	If CptHost is not running, continue
	Otherwise, exit silently
	"""
	for i in range(10):
		zoomprocess = subprocess.Popen('pgrep CptHost', shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
		zoompid, err = zoomprocess.communicate()

		if i == 9 and zoompid:
			return True
		if not zoompid:
			return False
		else:
			print("User is in a Zoom call, waiting...")
			time.sleep(30)

def run():
	"""
	Main function
	
	Validate the path to be used for receipt files and set a global var for the file path
	For each bundle ID specified as an input parameter from jamf, check if the app is running
	If not running, update the app and exit
	Otherwise, assuming the user is not in an active Zoom call, either force quit and update, or ask the user if they want to run the update
	If the latter and the user opts to update, run the update policy and notify the user once complete
	If the script exits due to an active Zoom call, we'll set a one hour deferral, but not count against their deferral limit
	"""
	global receipt_path
	receipt_path = "/Library/Application Support/{}/receipts".format(orgName)
	if not os.path.exists(receipt_path):
		os.makedirs(receipt_path)
		
	global receipt_file
	receipt_file = os.path.join(receipt_path, "install_{}.plist".format(POLICY_EVENT.replace(" ", "")))
	
	for bid in APPS:
		if not check_if_running(bid):
			print("App not running")
			run_update_policy(POLICY_EVENT)
			remove_daemons(POLICY_EVENT)
			sys.exit(0)
		else:
			check_install_date()
			if FORCE_QUIT:
				print("Notifying user and force quitting for emergency patch...")
				user_prompt(FORCE_MSG)
				quit_application(bid, force=True)
			else:
				if not check_for_zoom():
					print("No Zoom calls active, prompting user to update...")
					if user_prompt() or not PROMPT:
						quit_application(bid)
					else:
						print("Skipping update...")
						sys.exit(0)
				else:
					print("User is in an active Zoom call, skipping update prompt and deferring for one hour")
					set_deferral(3600, POLICY_EVENT)
					sys.exit(0)
			run_update_policy(POLICY_EVENT)
			print("Notifying user of update complete...")
			user_prompt(COMPLETE, bid, reopen_app=True)
			remove_daemons(POLICY_EVENT)

# main
if __name__ == "__main__":
	run()
	
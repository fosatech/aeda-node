import os
import threading
import subprocess
import asyncio
import requests
from flask import Flask, render_template, request, jsonify
from dotenv import load_dotenv
import git
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class FlaskServer:
	def __init__(self, port=5001):
		self.app = Flask(__name__)
		self.port = port
		self.setup_routes()
		self.thread = None

		load_dotenv()
		self.api_key = os.getenv('API_KEY', '')

		self.base_dir = os.getcwd()
		logger.info(f"Using base directory: {self.base_dir}")

		try:
			self.repo = git.Repo(self.base_dir)
			logger.info(f"Git repository found at: {self.base_dir}")
		except git.exc.InvalidGitRepositoryError:
			logger.error(f"Not a valid git repository: {self.base_dir}")
			parent_dir = os.path.dirname(self.base_dir)
			logger.info(f"Trying parent directory: {parent_dir}")
			try:
				self.repo = git.Repo(parent_dir)
				logger.info(f"Git repository found at: {parent_dir}")
				self.base_dir = parent_dir
			except git.exc.InvalidGitRepositoryError:
				logger.error(f"Not a valid git repository: {parent_dir}")
				self.repo = None

	def setup_routes(self):
		@self.app.route('/')
		def index():
			# api_key = os.getenv('API_KEY', '')
			return render_template('index.html', api_key=self.api_key)

		@self.app.route('/save_api_key', methods=['POST'])
		def save_api_key():
			api_key = request.form.get('api_key', '')
			env_path = os.path.join(self.base_dir, '.env')
			env_exists = os.path.exists(env_path)
			env_content = ""

			if env_exists:
				with open(env_path, 'r') as f:
					env_content = f.read()
				if 'API_KEY=' in env_content:
					env_lines = env_content.split('\n')
					new_lines = []
					for line in env_lines:
						if line.startswith('API_KEY='):
							new_lines.append(f'API_KEY={api_key}')
						else:
							new_lines.append(line)
					env_content = '\n'.join(new_lines)
				else:
					env_content += f'\nAPI_KEY={api_key}'
			else:
				env_content = f'API_KEY={api_key}'

			with open(env_path, 'w') as f:
				f.write(env_content)

			self.api_key = api_key
			return jsonify({"success": True})

		@self.app.route('/check_updates')
		def check_updates():
			return self._check_updates()


		@self.app.route('/update_and_restart')
		def update_and_restart():
			return self._update_and_restart()


	def _check_updates(self):
		"""Internal method to check for updates, reusable by route and async checker."""
		if not self.repo:
			return {"error": "Not a valid git repository"}
		try:
			self.repo.git.fetch('origin')
			current_commit = self.repo.head.commit.hexsha
			branch = self.repo.active_branch.name
			remote_commit = self.repo.git.rev_parse(f'origin/{branch}')
			has_updates = current_commit != remote_commit
			return {
					"has_updates": has_updates,
					"current_commit": current_commit[:7],
					"remote_commit": remote_commit[:7],
					"branch": branch
					}
		except Exception as e:
			logger.error(f"Error checking for updates: {str(e)}")
			return {"error": str(e)}


	def _update_and_restart(self):
		"""Internal method to update and restart, reusable by route and async checker."""
		if not self.repo:
			return {"error": "Not a valid git repository"}
		try:
			branch = self.repo.active_branch.name
			pull_info = self.repo.git.pull('origin', branch)
			script_path = os.path.join(self.base_dir, "update_script.sh")
			subprocess.run(['chmod', '+x', script_path])
			subprocess.Popen([script_path])
			return {
					"success": True,
					"message": "Update in progress. Application will restart shortly."
					}
		except Exception as e:
			logger.error(f"Error updating repository: {str(e)}")
			return {"error": str(e)}


	async def _async_check_for_updates_periodically(self):
		while True:
			try:
				logger.info("Checking for updates...")
				result = self._check_updates()
				if result.get('error'):
					logger.error(f"Update check failed: {result['error']}")
				elif result.get('has_updates', False):
					logger.info("Updates detected, initiating update and restart...")
					update_result = self._update_and_restart()
					if update_result.get('success'):
						logger.info("Update and restart initiated successfully")
					else:
						logger.error(f"Update failed: {update_result.get('error', 'Unknown error')}")
				else:
					logger.info("No updates available")
			except Exception as e:
				logger.error(f"Error in periodic update check: {str(e)}")
			await asyncio.sleep(20)


	def check_for_updates_periodically(self):
		try:
			loop = asyncio.get_running_loop()
		except RuntimeError:
			loop = asyncio.new_event_loop()
			asyncio.set_event_loop(loop)

		loop.run_until_complete(self._async_check_for_updates_periodically())


	def run(self):
		self.app.run(host='0.0.0.0', port=self.port, debug=False)

	def start(self, port=5001):
		self.thread = threading.Thread(target=self.run)
		self.thread.daemon = True
		self.thread.start()
		logger.info(f"Flask server started on port {self.port}")

		# uncomment for auto updates, still testing
		# update_thread = threading.Thread(target=self.check_for_updates_periodically)
		# update_thread.daemon = True
		# update_thread.start()
		# logger.info("Auto update checker thread started")

	def stop(self):
		if self.thread:
			logger.info("Flask server stopping...")

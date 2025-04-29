import socketio
import asyncio
import logging
import json

class SignalingClient:
	def __init__(self, server_url):
		self.server_url = server_url
		self.sio = socketio.AsyncClient()
		self.setup_events()

		# self.nodeId = None
		self.API_KEY = None

		self.SDR_HANDLER = None

		self.message_callback = None
		self.start_tdoa_callback = None
		self.start_scan_callback = None
		self.tdoa_settings_callback = None
		self.scan_settings_callback = None

		self.data_channel_callback = None

		self.ice_candidate_callback = None
		self.offer_callback = None
		# self.answer_callback = None

		
	def setup_events(self):

		@self.sio.on('connect', namespace='/nodes')
		async def on_connect():
			print(f"Connected to signaling server at {self.server_url}")
			response = await self.emit_with_response('register-node', {'key': self.API_KEY}, namespace='/nodes')
			if response.get('status') == 'success':
				print("[*] Node registered successfully!")
			else:
				print("[!] Node registration failed")


		@self.sio.on('startTdoa', namespace='/nodes')
		async def on_tdoa():
			print("[*] Got TDOA start")
			try:
				if self.start_tdoa_callback:
					await self.start_tdoa_callback()
			except Exception as e:
				print(f"[!] ERROR STARTING TDOA: {str(e)}")


		@self.sio.on('changeTdoaSettings', namespace='/nodes')
		async def tdoa_settings(data):
			print("[*] Got TDOA Settings")
			try:
				print(data)
				if self.tdoa_settings_callback:
					await self.tdoa_settings_callback(data)
			except Exception as e:
				print(f"[!] ERROR CHANGING TDOA SETTINGS: {str(e)}")


		@self.sio.on('changeScanSettings', namespace='/nodes')
		async def change_scan_settings(data):
			print("[*] Got scan settings")
			try:
				print(data)
				if self.scan_settings_callback:
					await self.scan_settings_callback(data)
			except Exception as e:
				print(f"[!] ERROR CHANGING SCAN SETTINGS: {str(e)}")


		@self.sio.on('startScan', namespace='/nodes')
		async def start_scan():
			print("[SignalingClient] Start Scan")
			try:
				await self.start_scan_callback()
			except Exception as e:
				print(f"[!] ICE error in socket: {str(e)}")


		# WebRTC Signaling
		@self.sio.on('ice-candidate', namespace='/nodes')
		async def ice_candidate(data):
			print("[*] Got ICE candidate")
			try:
				if self.ice_candidate_callback:
					await self.ice_candidate_callback(data)
			except Exception as e:
				print(f"[!] ICE error in socket: {str(e)}")


		@self.sio.on('offer', namespace='/nodes')
		async def on_offer(data):
			print("[*] Got offer")
			try:
				if self.offer_callback:
					await self.offer_callback(data)
			except Exception as e:
				print(f"[!] Offer error in socket: {str(e)}")


		@self.sio.on('startRTCStream', namespace='/nodes')
		async def start_rtc_stream():
			if self.data_channel_callback:
				await self.data_channel_callback(True)

		@self.sio.on('stopRTCStream', namespace='/nodes')
		async def stop_rtc_stream():
			if self.data_channel_callback:
				await self.data_channel_callback(False)


		@self.sio.on('setTriggerSettings', namespace='/nodes')
		async def set_trigger_settings(data):
			print("[*] Changing Trigger Settings")
			if data and self.SDR_HANDLER:
				self.SDR_HANDLER.trigger_db = data['dbLevel']
				self.SDR_HANDLER.trigger_bw = data['bandwidth']
				self.SDR_HANDLER.target_freq = data['targetFrequency']


		@self.sio.on('activateTrigger', namespace='/nodes')
		async def activate_trigger(data):
			print("[*] Activating Trigger")
			if data and self.SDR_HANDLER:
				self.SDR_HANDLER.trigger_active = True


		@self.sio.on('deactivateTrigger', namespace='/nodes')
		async def deactivate_trigger():
			print("[*] Deactivating Trigger")
			if self.SDR_HANDLER:
				self.SDR_HANDLER.trigger_active = False


	async def emit_with_response(self, event, data, namespace=None):
		future = asyncio.get_running_loop().create_future()

		def callback(response):
			future.set_result(response)

		await self.sio.emit(
				event, 
				data, 
				namespace=namespace,
				callback=callback
				)

		return await future


	
	async def connect(self):
		print(f"Connecting to signaling server at {self.server_url}")
		await self.sio.connect(self.server_url, namespaces=['/nodes'])


	async def send_message(self, header, message):
		await self.sio.emit(header, {"message": message}, namespace='/nodes')
	

	def set_on_tdoa(self, callback):
		self.on_tdoa_callback = callback

	def set_on_offer(self, callback):
		print("offerdata")
		callback()



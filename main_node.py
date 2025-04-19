import os
import asyncio
import sys
import msgpack
import socketio
import json
from aiortc import RTCPeerConnection, RTCSessionDescription, RTCIceCandidate, RTCDataChannel
from aiortc.contrib.signaling import object_from_string, object_to_string
from threading import Thread
from flask_server import FlaskServer
from dotenv import load_dotenv

import dsp_handler as DSP
from socketio_client import SignalingClient
from webrtc_client import WebRTCClient


class SDR_Handler:
	def __init__(self, dev_id):
		self.ws_handler = None
		self.rtc_handler = None

		# self.nodeId = nodeId
		self.dev_id = dev_id

		self.wideband_center_freq = 850e6
		self.wideband_bandwidth = 5e6

		self.target_freq = None
		self.reference_freq = None
		self.tdoa_samp_num = 2e6

		self.sdr = None
		self.scan = True

		self.sdr_lock = asyncio.Lock()

	async def capture_spectrogram(self):

		self.sdr = DSP.rtl_config(samp_rate=2.4e6)
		scan_output = await DSP.psd_scan(sdr=self.sdr, center_freq=91e6)

	async def start_wideband(self):
		print("[*] starting wideband")

		while self.scan:

			start_freq = int(self.wideband_center_freq) - (int(self.wideband_bandwidth) / 2)
			stop_freq = int(self.wideband_center_freq) + (int(self.wideband_bandwidth) / 2)

			# acquire lock before running scan
			async with self.sdr_lock:
				if not self.sdr:
					self.sdr = DSP.rtl_config(samp_rate=2.4e6, device_id=int(self.dev_id))

				samp_out = await DSP.psd_loop(self.sdr, start_freq=int(start_freq), stop_freq=int(stop_freq))
				packeted = msgpack.packb(samp_out, use_bin_type=True)
				if self.rtc_handler:
					await self.rtc_handler.send_data(packeted)

		print("[*] Exiting scan")


	async def capture_tdoa(self):

		try:
			if not self.target_freq or not self.reference_freq:
				print("[!] No target freq or reference set! Exiting!")
				return
			else:
				freq2 = float(self.target_freq) * 1e6
				freq1 = float(self.reference_freq) * 1e6
		except Exception as e:
			print(f"[!] ERROR IN TDOA CAPTURE: {e}")
			return

		N = int(self.tdoa_samp_num)
		maxN = int(1e5)

		async with self.sdr_lock:
			if self.sdr:
				self.sdr.close()
				self.sdr = None

			tdoa_task = asyncio.create_task(DSP.read_ext_samples(dev_id=self.dev_id, samp_num=N, freq1=freq1, freq2=freq2))
			samp_out = await tdoa_task

			samp_out = samp_out[:N*4]
			print(f"samp len {len(samp_out)}")

			try:
				index = 0
				while index < len(samp_out):
					packet = {
							"data": samp_out[index:index + maxN]
							}

					packeted = msgpack.packb(packet, use_bin_type=True)
					await self.ws_handler.send_message('tdoaOut', packeted)
					index += maxN

				end_pack = {
						"data": "none"
						}

				packeted_end = msgpack.packb(end_pack, use_bin_type=True)
				await self.ws_handler.send_message('tdoaOut', packeted_end)
			except Exception as e:
				print(e)


class MainNode:
	def __init__(self, dev_id=0, port=5000):
		self.socketio_handler = None
		self.rtc_handler = None
		self.sdr_handler = None

		# self.nodeId = nodeId
		self.dev_id = dev_id
		self.console_port = port
		
		self.tasks = []

		load_dotenv()
		self.API_KEY = os.getenv('API_KEY', '')

		with open(".node_args", "w") as f:
			f.write(f"{dev_id}")

		self.flask_server = FlaskServer(port=self.console_port)



	async def start(self):

		# start flask server
		self.flask_server.start()


		signaling_server = "https://olympus.fosa-tech.com"
		self.socketio_handler = SignalingClient(signaling_server)
		self.socketio_handler.API_KEY = self.API_KEY

		# callback handlers
		self.socketio_handler.message_callback = self.message_callback
		self.socketio_handler.start_tdoa_callback = self.start_tdoa_callback
		self.socketio_handler.start_scan_callback = self.start_scan_callback
		self.socketio_handler.tdoa_settings_callback = self.tdoa_settings_callback
		self.socketio_handler.scan_settings_callback = self.scan_settings_callback

		await self.socketio_handler.connect()

		
		# init webrtc handler
		self.rtc_handler = WebRTCClient(self.socketio_handler)

		# init sdr hander
		self.sdr_handler = SDR_Handler(self.dev_id)
		self.sdr_handler.ws_handler = self.socketio_handler
		self.sdr_handler.rtc_handler = self.rtc_handler

		self.rtc_handler.sdr_handler = self.sdr_handler

		# main loop
		while True:
			# await self.rtc_handler.send_ping()
			await asyncio.sleep(1)


	def message_callback(self, data):
		print(f"message callback data: {data}")
		

	
	async def start_tdoa_callback(self):
		print(f"[*] tdoa callback")
		await self.sdr_handler.capture_tdoa()


	async def start_scan_callback(self):
		print(f"[*] scan callback")
		self.sdr_handler.scan = True
		task = asyncio.create_task(self.sdr_handler.start_wideband())


	async def tdoa_settings_callback(self, data):
		print("[*] tdoa settings callback")
		print(data)

		if data['targetFrequency']:
			self.sdr_handler.target_freq = data['targetFrequency']

		if data['samples']:
			self.sdr_handler.tdoa_samp_num = float(data['samples']) * 1e6

		if data['referenceFrequency']:
			self.sdr_handler.reference_freq = data['referenceFrequency']

	async def scan_settings_callback(self, data):
		if data['centerFreq']:
			self.sdr_handler.wideband_center_freq = float(data['centerFreq']) * 1e6

		if data['bandwidth']:
			self.sdr_handler.wideband_bandwidth = float(data['bandwidth']) * 1e6





if __name__ == "__main__":
	script_args = sys.argv
	if len(script_args) > 1:
		node_id = script_args[1]
		dev_id = script_args[2]
		Node = MainNode(node_id, dev_id)
		asyncio.run(Node.start())
	else:
		print("NO ARGS!")



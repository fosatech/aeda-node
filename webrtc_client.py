import asyncio
import json
import aiortc
from aiortc import RTCPeerConnection, RTCSessionDescription, RTCIceCandidate, RTCDataChannel, RTCConfiguration, RTCIceServer, RTCIceGatherer
from aiortc.contrib.signaling import object_from_string, object_to_string



class WebRTCClient:
	def __init__(self, signaling_client):
		self.signaling_client = signaling_client
		
		self.signaling_client.ice_candidate_callback = self.on_ice_candidate
		self.signaling_client.offer_callback = self.on_offer
		self.signaling_client.data_channel_callback = self.toggle_data_channel
		self.sdr_handler = None

		self.data_channel_open = False

		self.config = RTCConfiguration(
			iceServers=[
				RTCIceServer(urls=["stun:stun3.l.google.com:19302"]),
				RTCIceServer(urls=["stun:stun4.l.google.com:19302"])
			]
		)

		self.data_channel = None
		self.pending_candidates = []

		self.pc = None


	async def toggle_data_channel(self, status):
		self.data_channel_open = status

	async def send_ping(self):
		while True:
			if self.data_channel:
				self.data_channel.send("1234")
			await asyncio.sleep(1)


	async def send_data(self, data):
		if self.data_channel and self.data_channel_open:
			try:
				self.data_channel.send(data)
			except Exception as e:
				print(f"[!] data channel error: {e}")



	def _create_peer_connection(self):

		print("[RTC Handler] Creating peer connection")
		self.pc = RTCPeerConnection(self.config)

		@self.pc.on("iceconnectionstatechange")
		async def on_iceconnectionstatechange():
			print(f"ICE connection state: {self.pc.iceConnectionState}")


		@self.pc.on("icegatheringstatechange")
		async def on_icegathering():
			print(self.pc.iceGatheringState)


		@self.pc.on("datachannel")
		async def on_datachannel(channel):
			print(f"Data channel established: {channel.label}")
			self.data_channel = channel

			@channel.on("open")
			async def on_open():
				print(f"Data channel '{channel.label}' opened")

			@channel.on("close")
			async def on_close():
				print(f"Data channel '{channel.label}' closed")
				await self.close_connection()

			@channel.on("message")
			async def on_message(message):
				print(f"Received message: {message}")



	async def on_ice_candidate(self, data_dict):
		print("[RTC Handler] Ice candidate data")
		data = data_dict['candidate']

		if not data:
			print("[RTC Handler] No data")
			return

		try:
			candidate = self.parse_candidate(data)

			if self.pc.remoteDescription and candidate:
				await self.pc.addIceCandidate(candidate)
			else:
				print("[RTC Handler] Queued pending candidate")
		except Exception as e:
			print("[!] Error adding ICE candidate:", e)


	async def on_offer(self, data):
		print("[RTC Handler] Offer")
		print(data)

		if not self.pc or not getattr(self.pc, "connectionState", None) == "connected":
			await self.close_connection()
			self._create_peer_connection()

			try:
				if data['sdp'] and data['type'] and self.pc:
					sdp = data['sdp']
					rtc_type = data['type']

					offer = RTCSessionDescription(sdp=sdp, type=rtc_type)
					await self.pc.setRemoteDescription(offer)

					for candidate in self.pending_candidates:
						await self.pc.addIceCandidate(candidate)
						print("Added candidate from queue")
					self.pending_candidates.clear()

					await self.pc.setLocalDescription(await self.pc.createAnswer())

					# Send to signalling
					answer = object_to_string(self.pc.localDescription)
					await self.signaling_client.send_message('answer', answer)
			except Exception as e:
				print("[!] [RTC Handler] Error!")
				print(e)



	async def close_connection(self):
		self.data_channel_open = False
		if self.sdr_handler:
			self.sdr_handler.scan = False


	# LMAO this is retarded, but okay aiortc
	def parse_candidate(self, data):
		print(data)

		# Split the candidate string after 'candidate:' and by spaces
		if data['candidate']:
			can_list = data['candidate'].split('candidate:')[1].split(' ')

			# Extract components based on their positions in the ICE candidate string
			foundation = can_list[0]  # '4065200437'
			component = int(can_list[1])
			protocol = can_list[2]	# 'udp'
			priority = int(can_list[3])  # '1677729535'
			ip = can_list[4]  # '209.206.91.241'
			port = int(can_list[5])  # '29356'
			type = can_list[7]	# 'srflx' (after 'typ')

			# Optional related address and port
			related_address = None
			related_port = None
			if 'raddr' in can_list:
				raddr_index = can_list.index('raddr')
				related_address = can_list[raddr_index + 1]  # '0.0.0.0'
				rport_index = can_list.index('rport')
				related_port = int(can_list[rport_index + 1])  # '0'


			ice_candidate = RTCIceCandidate(
					component=component,
					foundation=foundation,
					ip=ip,
					port=port,
					priority=priority,
					protocol=protocol,
					type=type,
					relatedAddress=related_address,
					relatedPort=related_port,
					sdpMid=data['sdpMid'],
					sdpMLineIndex=data['sdpMLineIndex']
					)

			return ice_candidate
		return None


import io
import math
import asyncio
import sys
import base64
import numpy as np
import matplotlib.pyplot as plt
from PIL import Image
from rtlsdr import RtlSdr
from scipy import signal


# TMP remove
stop_sdr = False


def format_samps(samp):
	samp_iq = np.frombuffer(samp, dtype=np.uint8)

	samp_out_I = samp_iq[0::2]
	samp_out_Q = samp_iq[1::2]

	samp_out_I = (samp_out_I.astype(np.float32) - 128) / 128.0
	samp_out_Q = (samp_out_Q.astype(np.float32) - 128) / 128.0

	samp_out = samp_out_I + 1j * samp_out_Q

	return samp_out



async def read_ext_samples(dev_id, samp_num, freq1, freq2):
	tdoa_prc_args = [
			"./.librtlsdr-2freq/build/src/rtl_sdr",
			"-f", str(freq1),
			"-h", str(freq2),
			"-d", str(dev_id),
			# "-s", "300000",
			"-g", "35",
			"-p", "-3",
			"-n", str(samp_num),
			# "-b", "512",
			# "-S",
			"-"
	]

	prc_args = tdoa_prc_args

	# TODO add for course NTP sync
	# delay = (time - datetime.now().timestamp())
	# await asyncio.sleep(delay)
	# print(f"after delay {datetime.now().timestamp()}")

	process = await asyncio.create_subprocess_exec(
			*prc_args,
			stdout=asyncio.subprocess.PIPE,
			stderr=asyncio.subprocess.PIPE
			)

	samp_out = bytearray()

	while True:
		chunk = await process.stdout.read(4096)
		if not chunk:
			break
		samp_out.extend(chunk)

	return samp_out


def rtl_config(samp_rate, freq_correction=None, device_id: int = 0):
	"""
	Configure RTL-SDR

	Args:
	samp_rate: Sample rate
	freq_correction: Frequency correction

	Returns sdr object or something
		test = True
		test = False

	Gain values:

	0, 9, 14, 27, 37, 77, 87, 125, 144, 157, 166, 197,
	207, 229, 254, 280, 297, 328, 338, 364, 372, 386,
	402, 421, 434, 439, 445, 480, 496
	"""

	sdr = RtlSdr(device_index=device_id)
	sdr.sample_rate = samp_rate

	print(f"configured sdr with: {device_id, samp_rate}")

	if freq_correction:
		sdr.freq_correction = freq_correction

	sdr.set_agc_mode(False)
	sdr.gain = 30
	print(sdr.valid_gains_db)


	return sdr


async def kill_sdr():
	stop_sdr = True


def _psd_plot(frequencies, psd):
	plt.rcParams['axes.facecolor'] = 'black'

	plt.semilogy(frequencies / 2e6, psd)
	plt.show()


def next_power_of_2(n):
	n = int(n)
	if n <= 0:
		return 1
	return 1 << (n - 1).bit_length()



def get_psd(sdr, freq, hop, crop_top, spec_size=2, deleted_samps=2048):
	"""
	Gets PSD data at center freq
	"""

	sdr.center_freq = float(freq)

	# Subtracts samp rate from freq hop
	crop_total = sdr.sample_rate - hop

	# Gets crop %
	crop_percent = (1 / sdr.sample_rate) * crop_total

	# sets min spec size
	N = spec_size
	if N < 1024:
		N = 1024

	sdr.read_samples(deleted_samps)
	samples = sdr.read_samples(N)

	normal = True

	# These will be updated soon, but works well enough for now
	if normal:

		window = signal.windows.hann(N)
		windowed_samples = samples * window

		fft_res = np.abs(np.fft.fft(windowed_samples))
		PSD = np.abs(fft_res) ** 2 / (N * np.sum(window ** 2))

		PSD_log = 10.0 * np.log10(PSD)
		PSD_shifted = np.fft.fftshift(PSD_log)

		crop_bin = int((crop_percent * len(PSD_shifted)) / 2)
		top_crop_bin = int((crop_top * (len(PSD_shifted) - (crop_bin * 2))))

		psd_cropped = PSD_shifted[crop_bin:-(crop_bin + top_crop_bin)]

	else:
		frequencies, psd = signal.welch(
				samples,
				fs=sdr.sample_rate,
				nperseg=N,
				detrend=False)

		crop_bin = int((crop_percent * len(psd)) / 2)
		top_crop_bin = int((crop_top * (len(psd) - (crop_bin * 2))))

		psd_db = 10 * np.log10(psd + 1e-12)

		crop_bins = int((crop_percent * len(psd_db)) / 2)
		psd_cropped = psd_db[crop_bin:-(crop_bin + top_crop_bin)]


	return psd_cropped



async def psd_loop(sdr, start_freq: int, stop_freq: int, target_freq, trigger_db, trigger_bw, trigger_active):

	"""
	Takes an SDR class from RtlSdr()

	Returns a freq array of db values
	"""

	hop_width = 1700000
	send_data = True

	psd = np.array([])
	freq = np.array([])

	scan_size = stop_freq - start_freq
	scan_steps = hop_width / scan_size

	spec_size = scan_steps * 2048
	spec_size = next_power_of_2(spec_size)



	if trigger_active:
		if target_freq and trigger_bw:
			target_freq = float(target_freq) * 1e6
			trigger_bw = float(trigger_bw) * 1e6

	psd_type = "PSD"

	for i in range(start_freq + int(hop_width / 2), stop_freq + int(hop_width / 2), hop_width):
		if not stop_sdr:
			crop_top = 0
			crop_hz = 0
			if (i + int(hop_width / 2)) > stop_freq:
				crop_hz = (i + int(hop_width / 2)) - stop_freq
				crop_top = (1 / hop_width) * crop_hz

			loop = asyncio.get_running_loop()
			new_psd = await loop.run_in_executor(None, lambda: get_psd(
				sdr=sdr,
				spec_size=spec_size,
				freq=i,
				hop=hop_width,
				crop_top=crop_top
			))

			# check for active trigger
			if trigger_active:

				trigger_start = target_freq - (trigger_bw / 2)
				trigger_stop = target_freq + (trigger_bw / 2)

				# lol this sucks
				if (i - hop_width) < trigger_stop and (i + hop_width) > trigger_start:
					cropped_hop = hop_width - crop_hz
					hz_percent = len(new_psd) / cropped_hop
					scan_start = i - (hop_width / 2)
					scan_stop = (i + (hop_width / 2)) - crop_hz

					start_diff = int((trigger_start - scan_start) * hz_percent)
					stop_diff = int((trigger_stop - scan_stop) * hz_percent)

					start_bin = start_diff if start_diff >= 0 else None
					stop_bin = stop_diff if stop_diff < 0 else None

					triggered = any(x > trigger_db for x in new_psd[start_bin:stop_bin])

					if triggered:
						print(f"TRIGGERED: {triggered}")

						scan_data = await psd_scan(sdr=sdr, center_freq=target_freq, bandwidth=trigger_bw)

						psd_type = "IMG"
						return scan_data, psd_type

			psd = np.append(psd, new_psd)
		else:
			sdr.close()
			send_data = False
			break

	if send_data:
		psd_list = list(psd)
		psd_len = len(psd_list)
		max_len = 20000

		if psd_len >= max_len:
			crop = math.ceil(psd_len / max_len)
			# naive crop to keep under max canvas width TODO replace with averaging
			psd_list = [psd_list[i] for i in range(len(psd_list)) if i % int(crop) == 0]

		return psd_list, psd_type


def convert_image_to_base64(image_buf):
	"""Convert a PIL Image buffer to base64 string"""
	# Get the binary data from the buffer
	img_data = image_buf.getvalue()

	# Encode as base64
	base64_encoded = base64.b64encode(img_data).decode('utf-8')

	return base64_encoded


async def psd_scan(sdr, center_freq, bandwidth, samps=None):

	samp_rate = 2.048e6
	num_rows = 512
	x = None

	if samps:
		x = samps
	else:
		record_time = 1 #sec

		total_samples = int(samp_rate * record_time)

		sdr.center_freq = center_freq

		sdr.read_samples(2048)
		x = sdr.read_samples(total_samples)

	x = x - np.mean(x)

	spectrogram_width = bandwidth

	bin_width = spectrogram_width / num_rows
	fft_size = int(np.round(sdr.sample_rate / bin_width))
	hop = int(total_samples / num_rows)

	spectrogram = np.zeros((num_rows, num_rows))

	for i in range(num_rows):
		start = i * hop
		if start + fft_size > total_samples:
			break
		window = x[start:start + fft_size]
		fft = np.fft.fftshift(np.fft.fft(window))
		center = fft_size // 2
		spectrogram[i, :] = 10 * np.log10(np.abs(fft[center - 256:center + 256]) ** 2)


	plt.figure(figsize=(512/100, 512/100), dpi=100)
	plt.axis('off')
	plt.gca().set_position([0, 0, 1, 1])
	plt.imshow(spectrogram, aspect='auto')

	buf = io.BytesIO()
	plt.savefig(buf, format='png', bbox_inches='tight', pad_inches=0)
	plt.close()
	buf.seek(0)

	binary_data = buf.getvalue()

	return binary_data



def main(start_freq:int, stop_freq:int):

	sdr = rtl_config(2.4e6)
	psd_scan(sdr, 96.5e6, 1024*256)
	sdr.close()


 
if __name__ == '__main__':
	pass
	# asyncio.run(main(850, 900))



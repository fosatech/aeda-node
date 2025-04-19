import io
import math
import asyncio
import sys
import base64
import numpy as np
import matplotlib.pyplot as plt
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



def get_psd(sdr, freq, hop, crop_top, spec_size=2):
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

	sdr.read_samples(2048)
	samples = sdr.read_samples(N)

	normal = True

	# These will be updated soon, but work well enough for now
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



async def psd_loop(sdr, start_freq: int, stop_freq: int):

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

	spec_size = scan_steps * 8192 
	spec_size = next_power_of_2(spec_size)
	print(f"scan steps: {scan_steps}")
	print(f"SPEC SIZE: {spec_size}")

	for i in range(start_freq + int(hop_width / 2), stop_freq + int(hop_width / 2), hop_width):
		if not stop_sdr:
			crop_top = 0
			if (i + int(hop_width / 2)) > stop_freq:
				crop_hz = (i + int(hop_width / 2)) - stop_freq
				crop_top = (1 / hop_width) * crop_hz

			loop = asyncio.get_running_loop()
			new_psd = await loop.run_in_executor(None, lambda: get_psd(sdr=sdr, spec_size=spec_size, freq=i, hop=hop_width, crop_top=crop_top))
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

		return psd_list


# old function for testing spec segmentation
async def psd_scan(sdr, center_freq, samps=1024*1024):
	
	sdr.center_freq = center_freq
	sdr.read_samples(2048)
	S = sdr.read_samples(samps)
	fft_size = 2048
	overlap = fft_size // 2

	freq, t, Sxx = signal.spectrogram(S, fs=2.4e6, nperseg=fft_size, noverlap=overlap)
	Sxx = np.fft.fftshift(Sxx, axes=0)
	freq = np.fft.fftshift(freq - 2.4e6 / 2)
	Sxx_dB = 10 * np.log10(Sxx + 1e-12)

	plt.figure(figsize=(Sxx_dB.shape[0]/100, Sxx_dB.shape[1]/100))	# Set figure size to match data dimensions
	plt.imshow(Sxx_dB.T, aspect='auto', cmap='viridis')
	plt.axis('off')
	plt.tight_layout(pad=0)

	buf = io.BytesIO()
	plt.savefig(buf, dpi=100, bbox_inches='tight', pad_inches=0)
	plt.close()

	buf.seek(0)
	img_byts = buf.getvalue()
	buf.close()

	print("encoding")
	encoded = base64.b64encode(img_byts).decode('utf-8')
	print("encoded")

	return img_byts


def main(start_freq:int, stop_freq:int):

	sdr = rtl_config(2.4e6)
	psd_scan(sdr, 96.5e6, 1024*256)
	sdr.close()


 
if __name__ == '__main__':
	asyncio.run(main(850, 900))



#!/usr/bin/env python3
import sys
import asyncio
from main_node import MainNode

if __name__ == "__main__":
	script_args = sys.argv
	if len(script_args) > 2:
		dev_id = script_args[1]
		console_port = script_args[2]
		Node = MainNode(dev_id=dev_id, port=console_port)
		asyncio.run(Node.start())
	else:
		print("Error: Missing required arguments!")
		print("Usage: python run.py [RTL-SDR Device Index (usually 0)] [console port]")
		sys.exit(1)

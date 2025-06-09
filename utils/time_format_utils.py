from datetime import datetime
import re


def time_difference(timestamp_str):
   """
   Convert a timestamp string (YYYY-MM-DD HH:MM:SS) into a time difference
   formatted as 'd h:m:s' relative to the current time.
   """
   # Convert input string to datetime object
   target_datetime = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")

   # Get current date and time
   now = datetime.now()

   # Compute time difference
   delta = abs(target_datetime - now)  # Use absolute difference to handle past/future timestamps

   # Extract days, hours, minutes, and seconds
   days = delta.days
   hours, remainder = divmod(delta.seconds, 3600)
   minutes, seconds = divmod(remainder, 60)

   # Format the output as 'd h:m:s'
   time_str = f"{days}d {hours}:{minutes:02}:{seconds:02}"
   return compact_uptime(time_str)


def compact_uptime(original_str, strip_secs=True):
   """
   Compact the uptime string into a shorter format without leading zeros
   and optionally strip seconds if strip_secs is True.
   """
   # Split the string into the two parts: days and time (hours:minutes:seconds)
   parts = original_str.split(" ")

   # Remove leading zeros from the day part (if any)
   formatted_days = parts[0][:-1].lstrip("0")  # Remove trailing 'd'

   # Split the time part into hours, minutes, and seconds
   time_parts = parts[1].split(":")
   hours = int(time_parts[0])  # Remove leading zeros from hours
   minutes = int(time_parts[1])  # Remove leading zeros from minutes
   seconds = int(time_parts[2])  # Remove leading zeros from seconds

   # Build the compact format
   compact_str = ""
   if hours > 0:
      compact_str = f"{hours}h{minutes}m"
   elif minutes > 0:
      compact_str = f"{minutes}m"
   else:
      strip_secs = False

   # Add days to the compact format if any
   compact_str = f"{formatted_days}d " + compact_str if formatted_days != "" else compact_str

   # Optionally add seconds to the compact format
   if not strip_secs:
      compact_str += f"{seconds}s"

   return compact_str


def split_time_string(time_string):
   """
   Split a time string (formatted as 'ddd d hh:mm:ss') into two separate parts.
   If only one time component is present, return it as the first part with empty second part.
   """
   time_string = time_string.strip()
   
   # Try to match two time components first
   match = re.match(r'(\d+d \d{2}:\d{2}:\d{2})\s+(\d+d \d{2}:\d{2}:\d{2})', time_string)
   if match:
      return match.groups()  # Returns tuple (first_part, second_part)
   
   # Try to match a single time component
   single_match = re.match(r'(\d+d \d{2}:\d{2}:\d{2})', time_string)
   if single_match:
      return single_match.group(1), ""  # Return single time with empty second part
   
   # Handle simple numeric uptime (assume seconds and convert to readable format)
   if time_string.isdigit():
      seconds = int(time_string)
      days, remainder = divmod(seconds, 86400)
      hours, remainder = divmod(remainder, 3600)
      minutes, seconds = divmod(remainder, 60)
      formatted_time = f"{days}d {hours:02}:{minutes:02}:{seconds:02}"
      return formatted_time, ""
   
   # If no patterns match, return the original string as first part
   return time_string, ""

# Some useful Google API documentation:
# https://developers.google.com/maps/documentation/directions/
# https://developers.google.com/maps/documentation/roads/snap

from API_KEYS import *
import googlemaps
import urllib, os
import numpy as np
import json
import polyline
import glob
import subprocess
import math
PHOTO_FOLDER = "./photos/"

# Adapted directly from Andrew Wheeler:
# https://andrewpwheeler.wordpress.com/2015/12/28/using-python-to-grab-google-street-view-imagery/
# Usage example:
# >>> download_streetview_image((46.414382,10.012988))
def download_streetview_image(apikey_streetview, lat_lon, filename="image", savepath=PHOTO_FOLDER, size="600x300", heading=151.78, pitch=-0, fi=".jpg", fov=90, get_metadata=False, verbose=True, outdoor=True, radius=15):
	assert type(radius) is int
	# Any size up to 640x640 is permitted by the API
	# fov is the zoom level, effectively. Between 0 and 120.
	base = "https://maps.googleapis.com/maps/api/streetview"
	if get_metadata:
		base = base + "/metadata?parameters"
	if type(lat_lon) is tuple:
		lat_lon_str = str(lat_lon[0]) + "," + str(lat_lon[1])
	elif type(lat_lon) is str:
		# We expect a latitude/longitude tuple, but if you providing a string address works too.
		lat_lon_str = lat_lon
	if outdoor:
		outdoor_string = "&source=outdoor"
	else:
		outdoor_string = ""
	url = base + "?size=" + size + "&location=" + lat_lon_str + "&heading=" + str(heading) + "&pitch=" + str(pitch) + "&fov=" + str(fov) + outdoor_string + "&radius" + str(radius) + "&key=" + apikey_streetview
	if verbose:
		print url
	if get_metadata:
		# Description of metadata API: https://developers.google.com/maps/documentation/streetview/intro#size
		response = urllib.urlopen(url)
		data = json.loads(response.read())
		return data
	else:
		urllib.urlretrieve(url, savepath+filename+fi)
		return savepath+filename+fi

# Gist copied from https://gist.github.com/jeromer/2005586 which is in the public domain:
def calculate_initial_compass_bearing(pointA, pointB):
	if (type(pointA) != tuple) or (type(pointB) != tuple):
		raise TypeError("Only tuples are supported as arguments")
	lat1 = math.radians(pointA[0])
	lat2 = math.radians(pointB[0])
	diffLong = math.radians(pointB[1] - pointA[1])
	x = math.sin(diffLong) * math.cos(lat2)
	y = math.cos(lat1) * math.sin(lat2) - (math.sin(lat1)
			* math.cos(lat2) * math.cos(diffLong))
	initial_bearing = math.atan2(x, y)
	initial_bearing = math.degrees(initial_bearing)
	compass_bearing = (initial_bearing + 360) % 360
	return compass_bearing

def haversine(a_gps, b_gps):
	"""
	Calculate the great circle distance between two points 
	on the earth (specified in decimal degrees)
	"""
	lat1, lon1 = a_gps
	lat2, lon2 = b_gps
	# convert decimal degrees to radians 
	lon1, lat1, lon2, lat2 = map(math.radians, [lon1, lat1, lon2, lat2])
	# haversine formula 
	dlon = lon2 - lon1 
	dlat = lat2 - lat1 
	a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
	c = 2 * math.asin(math.sqrt(a)) 
	km = 6367 * c
	m = 6367000.0 * c
	return m

# Given two GPS points (lat/lon), interpolate a sequence of GPS points in a straight line
def interpolate_points(a_gps,b_gps,n_points=10,hop_size=None):
	if hop_size is not None:
		distance = haversine(a_gps, b_gps)
		n_points = np.ceil(distance*1.0/hop_size)
	x = np.linspace(a_gps[0],b_gps[0],n_points)
	y = np.linspace(a_gps[1],b_gps[1],n_points)
	dense_points_list = zip(x,y)
	return dense_points_list
	# else:
	#	 print "You forgot to provide a hop parameter! Choose between:"
	#	 print "  n_points = number of points to interpolate;"
	#	 print "  hop_size = maximum distance between points in meters."

# Short script to process the lookpoints from the above "interpolate points" function.
def clean_look_points(look_points):
	# Remove points that are the same
	pt_diffs = [np.array(a)-np.array(b) for (a,b) in zip(look_points[:-1],look_points[1:])]
	keepers = np.abs(np.array(pt_diffs))>0
	look_points_out = [look_points[i] for i in range(len(keepers)) if np.any(keepers[i])]
	return look_points_out

# Download street view images for a sequence of GPS points.
# The orientation is assumed to be towards the next point.
# Setting orientation to value N orients the camera to the Nth next point.
# If there isn't a point N points in the future, we just use the previous heading.
def download_images_for_path(apikey_streetview, filestem, look_points, orientation=1):
	assert type(orientation) is int
	assert orientation >= 1
	for i in range(len(look_points)):
		gps_point = look_points[i]
		if i+orientation >= len(look_points):
			heading = prev_heading
		else:
			heading = calculate_initial_compass_bearing(gps_point, look_points[i+orientation])
		probe = download_streetview_image(apikey_streetview, gps_point, filename="", heading=heading, size="640x640", get_metadata=True)
		if probe['status']=="OK" and 'Google' in probe['copyright']:
			dest_file = download_streetview_image(apikey_streetview, gps_point, filename=filestem + str(i), heading=heading, size="640x640", get_metadata=False)
		prev_heading = heading

# Line up files in order to make a video using ffmpeg.
# ffmpeg requires all images files numbered in sequence, with no gaps.
# However, some images will not have been downloaded, so we need to shift everything to tidy up gaps.
# Also, some images will be duplicates, and we can remove them.
# Also, a user may want to manually discard images because they are clearly out of step with the path (e.g., they might be view inside a building, or slightly down a cross-street.) After manually removing files, re-running this will line up the files.
def line_up_files(filestem):
	files = glob.glob("./photos/"+filestem+"*.jpg")
	file_nums = [int(filename[9+len(filestem):-4]) for filename in files]
	file_sort = [files[i] for i in np.argsort(file_nums)]
	# First, remove file_nums that represent duplicate files
	file_keepers = [file_sort[0]]
	for i in range(1,len(file_sort)):
		prev_file = file_keepers[-1]
		curr_file = file_sort[i]
		result = os.system("diff " + curr_file + " " + prev_file)
		if result > 0:
			file_keepers += [curr_file]
	# Now, shuffle the files into a packed numbering:
	for i in range(len(file_keepers)):
		old_filename = file_keepers[i]
		new_filename = "./photos/{0}{1}.jpg".format(filestem,i)
		print "mv {0} {1}".format(old_filename, new_filename)
		os.system("mv {0} {1}".format(old_filename, new_filename))

def make_video(base_string, rate=20, video_string=None):
	if video_string is None:
		video_string = base_string
	subprocess.call("ffmpeg -r {0} -f image2 -s 600x600 -i ./photos/{1}%d.jpg -vcodec libx264 -crf 25 -pix_fmt yuv420p {2}.mp4".format(rate, base_string, video_string), shell=True)


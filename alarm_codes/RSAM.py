# RSAM  alarm to be run on list of channels
# Based on MATLAB code originally written by Matt Haney and Aaron Wech
#
# Wech 2017-06-08

import utils
from obspy import UTCDateTime
import numpy as np
from pandas import DataFrame
from os import remove
import time

# main function called by main.py
def run_alarm(config,T0):

	time.sleep(config.latency)
	SCNL=DataFrame.from_dict(config.SCNL)
	lvlv=np.array(SCNL['value'])
	scnl=SCNL['scnl'].tolist()
	stas=[sta.split('.')[0] for sta in scnl]

	t1 = T0-config.duration
	t2 = T0
	st = utils.grab_data(scnl,t1,t2,fill_value=0)

	#### preprocess data ####
	st.detrend('demean')
	st.taper(max_percentage=None,max_length=config.taper_val)
	st.filter('bandpass',freqmin=config.f1,freqmax=config.f2)

	#### calculate rsam ####
	rms=np.array([np.sqrt(np.mean(np.square(tr.data))) for tr in st])

	############################# Icinga message #############################
	state_message = ''.join('{}: {:.0f}/{}, '.format(sta,rms[i],lvlv[i]) for i,sta in enumerate(stas[:-1]))
	state_message = ''.join([state_message,'Arrestor ({}): {:.0f}/{}'.format(stas[-1],rms[-1],lvlv[-1])])
	###########################################################################

	if (rms[-1]<lvlv[-1]) & (sum(rms[:-1]>lvlv[:-1])>=config.min_sta):
		#### RSAM Detection!! ####
		##########################
		print('********** DETECTION **********')
		state_message='{} (UTC) RSAM detection! {}'.format(T0.strftime('%Y-%m-%d %H:%M'),state_message)
		state='CRITICAL'
		#### Generate Figure ####
		start = time.time()
		try:
			filename=make_figure(scnl,T0,config.alarm_name)
		except:
			filename=None
		### Send Email Notification ####
		craft_and_send_email(t1,t2,stas,rms,lvlv,config.alarm_name,filename)
		end = time.time()
		print('{:.2f} seconds to make figure & send email.'.format(end - start))
		#
	elif (rms[-1]<lvlv[-1]) & (sum(rms[:-1]>lvlv[:-1]/2)>=config.min_sta):
		#### elevated RSAM ####
		#######################
		state_message='{} (UTC) RSAM elevated! {}'.format(T0.strftime('%Y-%m-%d %H:%M'),state_message)
		state='WARNING'
		#
	elif sum(rms[:-1]!=0)<config.min_sta:
		#### not enough data ####
		#########################
		state_message='{} (UTC) data missing! {}'.format(T0.strftime('%Y-%m-%d %H:%M'),state_message)
		state='WARNING'
		#
	elif (rms[-1]>=lvlv[-1]) & (sum(rms[:-1]>lvlv[:-1])>=config.min_sta):
		### RSAM arrested ###
		#####################
		state_message='{} (UTC) RSAM normal (arrested). {}'.format(T0.strftime('%Y-%m-%d %H:%M'),state_message)
		state='WARNING'
		#
	else:
		#### RSAM normal ####
		#####################
		state_message='{} (UTC) RSAM normal. {}'.format(T0.strftime('%Y-%m-%d %H:%M'),state_message)
		state='OK'

	# send heartbeat status message to icinga
	utils.icinga_state(config.alarm_name,state,state_message)

def craft_and_send_email(t1,t2,stations,rms,lvlv,alarm_name,filename):
	from pandas import Timestamp

	# create the subject line
	subject='--- {} ---'.format(alarm_name)

	# create the text for the message you want to send
	message='Start: {} (UTC)\nEnd: {} (UTC)\n\n'.format(t1.strftime('%Y-%m-%d %H:%M'),t2.strftime('%Y-%m-%d %H:%M'))
	t1_local=Timestamp(t1.datetime,tz='UTC')
	t2_local=Timestamp(t2.datetime,tz='UTC')
	t1_local=t1_local.tz_convert('US/Alaska')
	t2_local=t2_local.tz_convert('US/Alaska')
	message='{}Start: {} ({})'.format(message,t1_local.strftime('%Y-%m-%d %H:%M'),t1_local.tzname())
	message='{}\nEnd: {} ({})\n\n'.format(message,t2_local.strftime('%Y-%m-%d %H:%M'),t2_local.tzname())

	a=np.array([''] * len(rms[:-1]))
	a[np.where(rms>lvlv)]='*'
	sta_message = ''.join('{}{}: {:.0f}/{}\n'.format(sta,a[i],rms[i],lvlv[i]) for i,sta in enumerate(stations[:-1]))
	sta_message = ''.join([sta_message,'\nArrestor: {} {:.0f}/{}'.format(stations[-1],rms[-1],lvlv[-1])])
	message = ''.join([message,sta_message])

	utils.send_alert(alarm_name,subject,message,filename)
	# utils.post_mattermost(subject,message,filename)
	utils.post_mattermost(subject,message,alarm_name,filename)
	# delete the file you just sent
	if filename:
		remove(filename)


def make_figure(scnl,T0,alarm_name):
	import matplotlib as m
	m.use('Agg')
	import matplotlib.pyplot as plt
	import matplotlib.cm as cm
	from matplotlib.colors import LinearSegmentedColormap
	from PIL import Image

	#### grab data ####
	start = time.time()	
	st = utils.grab_data(scnl,T0-3600, T0,fill_value='interpolate')
	end = time.time()
	print('{:.2f} seconds to grab figure data.'.format(end - start))

	#### preprocess data ####
	st.detrend('demean')
	[tr.decimate(2,no_filter=True) for tr in st if tr.stats.sampling_rate==100]
	[tr.decimate(2,no_filter=True) for tr in st if tr.stats.sampling_rate==50]
	[tr.resample(25) for tr in st if tr.stats.sampling_rate!=25]

	colors=cm.jet(np.linspace(-1,1.2,256))
	color_map = LinearSegmentedColormap.from_list('Upper Half', colors)
	plt.figure(figsize=(4.5,4.5))
	for i,tr in enumerate(st):
		ax=plt.subplot(len(st),1,i+1)
		tr.spectrogram(title='',log=False,samp_rate=25,dbscale=True,per_lap=0.5,mult=25.0,wlen=6,cmap=color_map,axes=ax)
		ax.set_yticks([3,6,9,12])
		ax.set_ylabel(tr.stats.station+'\n'+tr.stats.channel,fontsize=5,
															 rotation='horizontal',
													         multialignment='center',
													         horizontalalignment='right',
													         verticalalignment='center')
		ax.yaxis.set_ticks_position('right')
		ax.tick_params('y',labelsize=4)
		if i==0:
			ax.set_title(alarm_name+' Alarm')
		if i<len(st)-1:
			ax.set_xticks([])
		else:
			d_sec=np.linspace(0,3600,7)
			ax.set_xticks(d_sec)
			T=[tr.stats.starttime+dt for dt in d_sec]
			ax.set_xticklabels([t.strftime('%H:%M') for t in T])
			ax.tick_params('x',labelsize=5)
			ax.set_xlabel(tr.stats.starttime.strftime('%Y-%m-%d')+' UTC')


	plt.subplots_adjust(left=0.08,right=.94,top=0.92,bottom=0.1,hspace=0.1)
	filename=utils.tmp_figure_dir+'/'+UTCDateTime.utcnow().strftime('%Y%m%d_%H%M%S_%f')
	plt.savefig(filename,dpi=250,format='png')
	im=Image.open(filename)
	remove(filename)
	filename=filename+'.jpg'
	im.save(filename)

	return filename
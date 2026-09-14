package com.litongjava.whisper.android.java;

import android.app.*;
import android.content.*;
import android.media.*;
import android.os.*;
import com.whispercpp.java.whisper.WhisperContext;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.TimeUnit;

public class ListenService extends Service {
    public static final String ACTION_STOP="org.pavel.tabspeech.whisper.STOP";
    public static volatile boolean running=false;
    private static volatile String status="Готово",routeName="—";
    private static volatile long lastInferMs=0;
    private static volatile double rtf=0;
    private static volatile int dropped=0;
    private final ArrayBlockingQueue<float[]> queue=new ArrayBlockingQueue<>(2);
    private volatile boolean stopRequested=false,captureDone=false;
    private AudioRecord recorder; private AudioManager audio; private PowerManager.WakeLock wake;
    private boolean bluetooth; private String language; private WhisperContext whisper; private int oldMode;

    public static String statusText(){
        String perf=lastInferMs>0?String.format(java.util.Locale.US,"\nОбработка: %.2f с · RTF %.2f · отброшено чанков: %d",lastInferMs/1000.0,rtf,dropped):"";
        String speed=rtf>1.0?"\n⚠ Whisper не успевает за речью на этом устройстве.":"";
        return status+"\nМикрофон: "+routeName+perf+speed;
    }
    @Override public android.os.IBinder onBind(Intent i){return null;}
    @Override public int onStartCommand(Intent intent,int flags,int id){
        if(intent!=null&&ACTION_STOP.equals(intent.getAction())){requestStop();return START_NOT_STICKY;}
        if(running)return START_NOT_STICKY;
        language=intent!=null?intent.getStringExtra("lang"):"de"; bluetooth=intent!=null&&intent.getBooleanExtra("bluetooth",false);
        startForegroundNow(); running=true;stopRequested=false;captureDone=false;dropped=0;lastInferMs=0;rtf=0;
        wake=((PowerManager)getSystemService(POWER_SERVICE)).newWakeLock(PowerManager.PARTIAL_WAKE_LOCK,"TabSpeechWhisper:listen");wake.acquire();
        new Thread(this::inferenceLoop,"whisper-inference").start(); new Thread(this::captureLoop,"audio-capture").start(); return START_NOT_STICKY;
    }
    private void startForegroundNow(){
        NotificationManager nm=(NotificationManager)getSystemService(NOTIFICATION_SERVICE);nm.createNotificationChannel(new NotificationChannel("listen","Распознавание речи",NotificationManager.IMPORTANCE_LOW));
        int flags=PendingIntent.FLAG_UPDATE_CURRENT|(Build.VERSION.SDK_INT>=23?PendingIntent.FLAG_IMMUTABLE:0);
        PendingIntent open=PendingIntent.getActivity(this,0,new Intent(this,MainActivity.class),flags);
        PendingIntent stop=PendingIntent.getService(this,1,new Intent(this,ListenService.class).setAction(ACTION_STOP),flags);
        Notification n=new Notification.Builder(this,"listen").setSmallIcon(android.R.drawable.ic_btn_speak_now).setContentTitle("TabSpeech Whisper: микрофон включён").setContentText("Аудио только в RAM").setContentIntent(open).addAction(android.R.drawable.ic_media_pause,"Остановить",stop).setOngoing(true).build();startForeground(1,n);
    }
    private void captureLoop(){
        final int sr=16000,chunkSamples=sr*3;short[] segment=new short[chunkSamples];int pos=0;
        try{
            audio=(AudioManager)getSystemService(AUDIO_SERVICE);oldMode=audio.getMode();AudioDeviceInfo chosen=null;
            if(bluetooth){audio.setMode(AudioManager.MODE_IN_COMMUNICATION);audio.startBluetoothSco();audio.setBluetoothScoOn(true);long until=System.currentTimeMillis()+8000;while(!stopRequested&&chosen==null&&System.currentTimeMillis()<until){for(AudioDeviceInfo d:audio.getDevices(AudioManager.GET_DEVICES_INPUTS))if(d.getType()==AudioDeviceInfo.TYPE_BLUETOOTH_SCO){chosen=d;break;}if(chosen==null)Thread.sleep(100);}if(chosen==null)throw new IOException("Bluetooth-микрофон не найден");}
            else for(AudioDeviceInfo d:audio.getDevices(AudioManager.GET_DEVICES_INPUTS))if(d.getType()==AudioDeviceInfo.TYPE_BUILTIN_MIC){chosen=d;break;}
            int min=AudioRecord.getMinBufferSize(sr,AudioFormat.CHANNEL_IN_MONO,AudioFormat.ENCODING_PCM_16BIT);if(min<=0)throw new IOException("PCM 16 кГц не поддерживается");
            recorder=new AudioRecord(MediaRecorder.AudioSource.VOICE_RECOGNITION,sr,AudioFormat.CHANNEL_IN_MONO,AudioFormat.ENCODING_PCM_16BIT,Math.max(min*2,6400));
            if(recorder.getState()!=AudioRecord.STATE_INITIALIZED)throw new IOException("Не удалось открыть микрофон");if(chosen!=null&&!recorder.setPreferredDevice(chosen))throw new IOException("Не удалось выбрать микрофон");recorder.startRecording();short[] read=new short[1600];
            while(!stopRequested){int n=recorder.read(read,0,read.length);if(n<0){if(stopRequested)break;throw new IOException("Ошибка AudioRecord: "+n);}AudioDeviceInfo routed=recorder.getRoutedDevice();if(routed!=null)routeName=String.valueOf(routed.getProductName());for(int i=0;i<n;i++){segment[pos++]=read[i];if(pos==segment.length){offerPcm(segment,pos);segment=new short[chunkSamples];pos=0;}}status="Слушаю "+language.toUpperCase()+" · чанки 3 с · звук не сохраняется";}
        }catch(Throwable e){if(!stopRequested)status="Ошибка микрофона: "+e.getMessage();}
        finally{if(pos>=8000)offerPcm(segment,pos);captureDone=true;AudioRecord r=recorder;recorder=null;if(r!=null){try{r.stop();}catch(Exception ignored){}r.release();}if(audio!=null){if(bluetooth){audio.stopBluetoothSco();audio.setBluetoothScoOn(false);}audio.setMode(oldMode);}}
    }
    private void offerPcm(short[] pcm,int count){double sum=0;for(int i=0;i<count;i++){double v=pcm[i]/32768.0;sum+=v*v;}double rms=Math.sqrt(sum/Math.max(1,count));if(rms<0.002)return;float[] f=new float[count];for(int i=0;i<count;i++)f[i]=pcm[i]/32768.0f;if(!queue.offer(f)){queue.poll();dropped++;queue.offer(f);}}
    private void inferenceLoop(){
        try{status="Загрузка Whisper small…";whisper=WhisperContext.createContextFromAsset(getAssets(),"models/ggml-small.bin");status="Whisper small загружен. Ожидаю речь…";while(!captureDone||!queue.isEmpty()){float[] data=queue.poll(300,TimeUnit.MILLISECONDS);if(data==null)continue;long t0=SystemClock.elapsedRealtime();String text=whisper.transcribeData(data,language).trim();long elapsed=SystemClock.elapsedRealtime()-t0;lastInferMs=elapsed;rtf=elapsed/(data.length/16000.0*1000.0);if(!text.isEmpty())appendText(text);}status="Остановлено. Очередь обработана.";}
        catch(Throwable e){status="Ошибка Whisper: "+e.getMessage();}
        finally{try{if(whisper!=null)whisper.release();}catch(Exception ignored){}whisper=null;running=false;if(wake!=null&&wake.isHeld())wake.release();stopForeground(true);stopSelf();}
    }
    private synchronized void appendText(String s)throws IOException{try(FileOutputStream out=openFileOutput("transcript.txt",MODE_APPEND)){out.write((s+"\n").getBytes(StandardCharsets.UTF_8));}}
    private void requestStop(){stopRequested=true;status="Останавливаю… завершаю последние фрагменты";AudioRecord r=recorder;if(r!=null)try{r.stop();}catch(Exception ignored){}}
    @Override public void onDestroy(){requestStop();super.onDestroy();}
}

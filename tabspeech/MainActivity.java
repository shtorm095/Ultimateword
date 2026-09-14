package com.litongjava.whisper.android.java;

import android.app.*;
import android.os.*;
import android.content.*;
import android.content.pm.PackageManager;
import android.graphics.*;
import android.graphics.pdf.PdfDocument;
import android.net.Uri;
import android.widget.*;
import java.io.*;
import java.text.SimpleDateFormat;
import java.util.*;

public class MainActivity extends Activity {
    private TextView status, transcript;
    private Spinner language, input;
    private final Handler handler = new Handler(Looper.getMainLooper());
    private String pdfSnapshot = "";
    private final Runnable refresh = new Runnable() {
        @Override public void run() {
            status.setText(ListenService.statusText());
            transcript.setText(readTranscript());
            handler.postDelayed(this, 500);
        }
    };

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(24, 18, 24, 12);
        setContentView(root);
        TextView title = new TextView(this);
        title.setText("TabSpeech Whisper small · v0.2\nЛокально · аудио только в RAM");
        title.setTextSize(21); root.addView(title);
        language = new Spinner(this);
        language.setAdapter(new ArrayAdapter<String>(this, android.R.layout.simple_spinner_dropdown_item,
                new String[]{"Deutsch", "English"})); root.addView(language);
        input = new Spinner(this);
        input.setAdapter(new ArrayAdapter<String>(this, android.R.layout.simple_spinner_dropdown_item,
                new String[]{"Микрофон планшета", "Bluetooth / AirPods"})); root.addView(input);
        LinearLayout row = new LinearLayout(this); row.setOrientation(LinearLayout.HORIZONTAL);
        addButton(row, "Начать", this::start); addButton(row, "Стоп", this::stop); addButton(row, "PDF", this::exportPdf); root.addView(row);
        addButton(root, "Новый разговор", this::clearTranscript);
        status = new TextView(this); status.setTextSize(13); status.setPadding(0,8,0,8); root.addView(status);
        ScrollView sv = new ScrollView(this); transcript = new TextView(this); transcript.setTextSize(17); transcript.setTextIsSelectable(true);
        sv.addView(transcript); root.addView(sv, new LinearLayout.LayoutParams(-1,0,1));
    }

    private void addButton(LinearLayout parent, String text, Runnable action) {
        Button b = new Button(this); b.setText(text); b.setOnClickListener(v -> action.run());
        parent.addView(b, parent.getOrientation()==LinearLayout.HORIZONTAL ? new LinearLayout.LayoutParams(0,-2,1) : new LinearLayout.LayoutParams(-1,-2));
    }

    private void start() {
        if (ListenService.running) { toast("Уже работает"); return; }
        if (checkSelfPermission(android.Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{android.Manifest.permission.RECORD_AUDIO},10); return;
        }
        Intent i = new Intent(this, ListenService.class);
        i.putExtra("lang", language.getSelectedItemPosition()==0 ? "de" : "en");
        i.putExtra("bluetooth", input.getSelectedItemPosition()==1);
        startForegroundService(i);
    }
    private void stop() { startService(new Intent(this,ListenService.class).setAction(ListenService.ACTION_STOP)); }
    @Override public void onRequestPermissionsResult(int r,String[] p,int[] g){super.onRequestPermissionsResult(r,p,g);if(r==10&&g.length>0&&g[0]==PackageManager.PERMISSION_GRANTED)start();else toast("Нужно разрешение микрофона");}

    private String readTranscript() {
        File f=new File(getFilesDir(),"transcript.txt"); if(!f.isFile())return "";
        try { ByteArrayOutputStream out=new ByteArrayOutputStream(); try(InputStream in=new FileInputStream(f)){byte[] b=new byte[8192];int n;while((n=in.read(b))>0)out.write(b,0,n);} return out.toString("UTF-8"); }
        catch(Exception e){return "Ошибка чтения текста: "+e.getMessage();}
    }
    private void clearTranscript(){if(ListenService.running){toast("Сначала остановите распознавание");return;}new AlertDialog.Builder(this).setMessage("Удалить текущий текст? Сохранённые PDF останутся.").setNegativeButton("Отмена",null).setPositiveButton("Удалить",(d,w)->{new File(getFilesDir(),"transcript.txt").delete();transcript.setText("");}).show();}
    private void exportPdf(){if(ListenService.running){toast("Сначала нажмите Стоп и дождитесь окончания обработки");return;}pdfSnapshot=readTranscript();if(pdfSnapshot.trim().isEmpty()){toast("Пока нет текста");return;}Intent i=new Intent(Intent.ACTION_CREATE_DOCUMENT).setType("application/pdf").addCategory(Intent.CATEGORY_OPENABLE);i.putExtra(Intent.EXTRA_TITLE,"TabSpeech-"+new SimpleDateFormat("yyyyMMdd-HHmm",Locale.US).format(new Date())+".pdf");startActivityForResult(i,20);}
    @Override protected void onActivityResult(int r,int c,Intent data){super.onActivityResult(r,c,data);if(r!=20||c!=RESULT_OK||data==null)return;try{writePdf(data.getData(),pdfSnapshot);toast("PDF сохранён");}catch(Exception e){toast("Ошибка PDF: "+e.getMessage());}}
    private void writePdf(Uri uri,String text)throws Exception{
        PdfDocument pdf=new PdfDocument(); Paint p=new Paint(Paint.ANTI_ALIAS_FLAG);p.setTextSize(12);p.setColor(Color.BLACK);int pageNo=0;PdfDocument.Page page=null;float y=0;
        try{for(String paragraph:text.split("\\n",-1)){String rest=paragraph;do{if(page==null||y>800){if(page!=null)pdf.finishPage(page);page=pdf.startPage(new PdfDocument.PageInfo.Builder(595,842,++pageNo).create());y=40;page.getCanvas().drawText("TabSpeech Whisper small — автоматическая расшифровка",40,y,p);y+=24;}int n=rest.isEmpty()?0:p.breakText(rest,true,515,null);if(n>0&&n<rest.length()){int sp=rest.lastIndexOf(' ',n);if(sp>0)n=sp;}page.getCanvas().drawText(rest.substring(0,n),40,y,p);y+=17;rest=rest.substring(n).trim();}while(!rest.isEmpty());}if(page!=null)pdf.finishPage(page);try(OutputStream out=getContentResolver().openOutputStream(uri)){pdf.writeTo(out);}}finally{pdf.close();}}
    private void toast(String s){Toast.makeText(this,s,Toast.LENGTH_LONG).show();}
    @Override protected void onResume(){super.onResume();handler.post(refresh);}
    @Override protected void onPause(){handler.removeCallbacks(refresh);super.onPause();}
}

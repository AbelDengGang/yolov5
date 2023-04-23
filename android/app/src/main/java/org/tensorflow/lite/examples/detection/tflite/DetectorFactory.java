package org.tensorflow.lite.examples.detection.tflite;

import android.content.res.AssetManager;
import android.util.Log;

import com.esotericsoftware.yamlbeans.YamlException;
import com.esotericsoftware.yamlbeans.YamlReader;

import java.io.BufferedReader;
import java.io.File;
import java.io.FileNotFoundException;
import java.io.FileReader;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.util.Map;

public class DetectorFactory {
    public static YoloV5Classifier getDetector(
            final AssetManager assetManager,
            final String modelFilename)
            throws IOException {
        String labelFilename = null;
        boolean isQuantized = false;
        int inputSize = 0;
        int[] output_width = new int[]{0};
        int[][] masks = new int[][]{{0}};
        int[] anchors = new int[]{0};

        try{
            YamlReader reader = null;
            InputStream labelsInput = assetManager.open("coco.yaml");
            BufferedReader br = new BufferedReader(new InputStreamReader(labelsInput));
            String line;

            reader = new YamlReader(new InputStreamReader(labelsInput));
            Object object = reader.read();
            Map map = (Map)object;
            //String ret =(String) map.get("path");
            Log.e("aaaa","path" + (String) map.get("path"));
            Map names = (Map) map.get("names");
            int name_size = names.size();
            Log.e("aaaa","name count = " + name_size);
            Object keys = names.keySet();
            for(int i= 0;i<name_size;i++){
                Log.e("aaaa",i + " " + (String)names.get(Integer.toString(i)));
            }
            Log.e("aaaa","aaa");
        } catch (FileNotFoundException | YamlException e) {
            e.printStackTrace();
        }

        if (modelFilename.equals("yolov5s.tflite")) {
            labelFilename = "file:///android_asset/coco.txt";
            isQuantized = false;
            inputSize = 640;
            output_width = new int[]{80, 40, 20};
            masks = new int[][]{{0, 1, 2}, {3, 4, 5}, {6, 7, 8}};
            anchors = new int[]{
                    10,13, 16,30, 33,23, 30,61, 62,45, 59,119, 116,90, 156,198, 373,326
            };
        }
        else if (modelFilename.equals("yolov5s-fp16.tflite")) {
            labelFilename = "file:///android_asset/coco.txt";
            isQuantized = false;
            inputSize = 320;
            output_width = new int[]{40, 20, 10};
            masks = new int[][]{{0, 1, 2}, {3, 4, 5}, {6, 7, 8}};
            anchors = new int[]{
                    10,13, 16,30, 33,23, 30,61, 62,45, 59,119, 116,90, 156,198, 373,326
            };
        }
        else if (modelFilename.equals("yolov5s-int8.tflite")) {
            labelFilename = "file:///android_asset/coco.txt";
            isQuantized = true;
            inputSize = 320;
            output_width = new int[]{40, 20, 10};
            masks = new int[][]{{0, 1, 2}, {3, 4, 5}, {6, 7, 8}};
            anchors = new int[]{
                    10,13, 16,30, 33,23, 30,61, 62,45, 59,119, 116,90, 156,198, 373,326
            };
        }
        return YoloV5Classifier.create(assetManager, modelFilename, labelFilename, isQuantized,
                inputSize);
    }

}

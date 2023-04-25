package org.tensorflow.lite.examples.detection.env;

public class GlobalConfig {
    public static  int inputSourceType = 0; // 0 本地相机；1 assert图片；2 其他图片;3 网络
    public static int getInputSourceType(){
        return inputSourceType;
    }
    public static void setInputSourceType(int type){
        inputSourceType = type;
    }
    public static String assertPicName="kite.jpg";
    public static String getAssertPicName(){
        return assertPicName;
    }
    public static void setAssertPicName(String name){
        assertPicName=name;
    }
}

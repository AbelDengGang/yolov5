## Info
This branch provides detection and Android code complement to branch `tf-only-export`.
`models/tf.py` uses TF2 API to construct a tf.Keras model according to `*.yaml` config files and reads weights from `*.pt`, without using ONNX. 

**Because this branch persistently rebases to master branch of ultralytics/yolov5, use `git pull --rebase` instead of `git pull`.**

## Usage
### 1. Git clone `yolov5` and checkout `tf-android-tfl-detect`
```
git clone https://github.com/zldrobit/yolov5.git
cd yolov5
git checkout tf-android-tfl-detect
```
and download pretrained weights from 
```
https://github.com/ultralytics/yolov5.git
```

### 2. Install requirements
```
pip install -r requirements.txt
pip install tensorflow==2.4.0
```

### 3. Convert and verify
- Convert weights to TensorFlow SavedModel and GraphDef, and verify them with
```
PYTHONPATH=. python models/tf.py --weights weights/yolov5s.pt --cfg models/yolov5s.yaml --img 320
python3 detect.py --weight weights/yolov5s.pb --img 320
python3 detect.py --weight weights/yolov5s_saved_model/ --img 320
```
- Convert weights to TensorFlow SavedModel and GraphDef **integrated with NMS**, and verify them with
```
PYTHONPATH=. python3  models/tf.py --img 320 --weight weights/yolov5s.pt --cfg models/yolov5s.yaml --tf-nms
python3 detect.py --img 320 --weight weights/yolov5s.pb --no-tf-nms
python3 detect.py --img 320 --weight weights/yolov5s_saved_model --no-tf-nms
```
- Convert weights to fp16 TFLite model, and verify it with
```
PYTHONPATH=. python3  models/tf.py --weight weights/yolov5s.pt --cfg models/yolov5s.yaml --img 320 --no-tfl-detect
python3 detect.py --weight weights/yolov5s-fp16.tflite --img 320 --tfl-detect
```
- Convert weights to int8 TFLite model, and verify it with (Post-Training Quantization needs train or val images from [COCO 2017 dataset](https://cocodataset.org/#download))
```
PYTHONPATH=. python3  models/tf.py --weight weights/yolov5s.pt --cfg models/yolov5s.yaml --img 320 --no-tfl-detect --tfl-int8 --source /data/dataset/coco/coco2017/train2017 --ncalib 100
python3 detect.py --weight weights/yolov5s-int8.tflite --img 320 --tfl-int8 --tfl-detect
```
- Convert full int8 TFLite model to **Edge TPU** and verify it with
```
# need Edge TPU runtime https://coral.ai/software/#edgetpu-runtime
# and Edge TPU compiler https://coral.ai/software/#debian-packages
mkdir edgetpu
edgetpu_compiler -s -a -o edgetpu weights/yolov5s-int8.tflite
python3 detect.py --weight edgetpu/yolov5s-int8_edgetpu.tflite --edgetpu --tfl-int8 --tfl-detect --img 320
```


### 4. Put TFLite models in `assets` folder of Android project, and change 
- `inputSize` to `--img`
- `output_width` according to new/old `inputSize` ratio
- `anchors` to `m.anchor_grid` as https://github.com/ultralytics/yolov5/pull/1127#issuecomment-714651073
in android/app/src/main/java/org/tensorflow/lite/examples/detection/tflite/DetectorFactory.java

Then run the program in Android Studio.

If you have further question, plz ask in https://github.com/ultralytics/yolov5/pull/1127

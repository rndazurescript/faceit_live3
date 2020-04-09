import imageio
import numpy as np
import pandas as pd
from skimage.transform import resize
import warnings
import sys
import cv2
import time
import PIL.Image as Image
import PIL.ImageFilter
import io
from io import BytesIO
import pyfakewebcam
import pyautogui
import os
import glob
from argparse import Namespace
import argparse
import timeit
warnings.filterwarnings("ignore")

############## setup ####
stream = True
media_path = './media/'
model_path = 'model/'

parser = argparse.ArgumentParser()
parser.add_argument('--webcam_id', type = int, default = 2)
parser.add_argument('--stream_id', type = int, default = 1)
args = parser.parse_args()


webcam_id = args.webcam_id
webcam_height = 480
webcam_width = 640
screen_width, screen_height = pyautogui.size()

stream_id = args.stream_id
first_order_path = 'first-order-model/'
sys.path.insert(0,first_order_path)
reset = True

# import methods from first-order-model
import demo
from demo import load_checkpoints, make_animation, tqdm

# prevent tqdm from outputting to console
demo.tqdm = lambda *i, **kwargs: i[0]

img_list = []
for filename in os.listdir(media_path):
    if filename.endswith(".jpg") or filename.endswith(".jpeg") or filename.endswith(".png"):
        img_list.append(os.path.join(media_path, filename))
        print(os.path.join(media_path, filename))

print(img_list, len(img_list))





############## end setup ####

def main():
    global source_image
    source_image =  readnextimage(0)

    # start streaming
    camera = pyfakewebcam.FakeWebcam(f'/dev/video{stream_id}', webcam_width, webcam_height)
    camera.print_capabilities()
    print(f"Fake webcam created on /dev/video{stream}. Use Firefox and join a Google Meeting to test.")

    # capture webcam
    video_capture = cv2.VideoCapture(webcam_id)
    time.sleep(1)
    width = video_capture.get(3)  # float
    height = video_capture.get(4) # float
    print("webcam dimensions = {} x {}".format(width,height))

    # load models
    previous = None
    net = load_face_model()
    generator, kp_detector = demo.load_checkpoints(config_path=f'{first_order_path}config/vox-adv-256.yaml', checkpoint_path=f'{model_path}/vox-adv-cpk.pth.tar')

    
    # create windows
    cv2.namedWindow('Face', cv2.WINDOW_GUI_NORMAL) # extracted face
    cv2.moveWindow('Face', int(screen_width/2)-150, 100)
    cv2.resizeWindow('Face', 256,256)

    cv2.namedWindow('DeepFake', cv2.WINDOW_GUI_NORMAL) # face transformation
    cv2.moveWindow('DeepFake', int(screen_width/2)+150, 100)
    cv2.resizeWindow('DeepFake', 256,256)


    cv2.namedWindow('Stream', cv2.WINDOW_GUI_NORMAL) # rendered to fake webcam
    cv2.moveWindow('Stream', int(screen_width/2)-int(webcam_width/2), 400)
    cv2.resizeWindow('Stream', webcam_width,webcam_width)

    
    print("Press C to center Webcam, Press N for next image in media directory")

    while True:
        ret, frame = video_capture.read()
        frame = cv2.resize(frame, (640, 480))
        frame = cv2.flip(frame,1)

        if (previous is None or reset is True):
            x1,y1,x2,y2 = find_face_cut(net,frame)
            previous = cut_face_window(x1,y1,x2,y2,source_image)
            reset = False

        deep_fake = process_image(previous,cut_face_window(x1,y1,x2,y2,frame),net, generator, kp_detector)
        deep_fake = cv2.cvtColor(deep_fake, cv2.COLOR_RGB2BGR) 

        #cv2.imshow('Webcam', frame) - get face
        cv2.imshow('Face', cut_face_window(x1,y1,x2,y2,frame))
        cv2.imshow('DeepFake', deep_fake)


        rgb = cv2.resize(deep_fake,(480,480))
        # pad image 
        stream_v = cv2.copyMakeBorder( rgb, 0, 0, 80, 80, cv2.BORDER_CONSTANT)
        cv2.imshow('Stream',stream_v)
        
        #time.sleep(1/30.0)
        stream_v = cv2.flip(stream_v,1)
        stream_v = cv2.cvtColor(stream_v, cv2.COLOR_BGR2RGB)
        stream_v = (stream_v*255).astype(np.uint8)

        # stream to fakewebcam
        camera.schedule_frame(stream_v)


        k = cv2.waitKey(1) 
        # Hit 'q' on the keyboard to quit!
        if k & 0xFF == ord('q'):
            video_capture.release()
            break
        elif k==ord('c'):
            # center
            reset = True
        elif k==ord('n'):
            # rotate images
            source_image = readnextimage()
            reset = True

    cv2.destroyAllWindows()
    exit()


# transform face with first-order-model
def process_image(base,current,net, generator,kp_detector):
    predictions = make_animation(source_image, [base,current], generator, kp_detector, relative=False, adapt_movement_scale=False)
    return predictions[1]

def load_face_model():
    modelFile = f"{model_path}/res10_300x300_ssd_iter_140000.caffemodel"
    configFile = f"{model_path}./deploy.prototxt.txt"
    net = cv2.dnn.readNetFromCaffe(configFile, modelFile)
    return net

def cut_face_window(x1,y1,x2,y2,face):
    cut_x1 = x1
    cut_y1 = y1
    cut_x2 = x2
    cut_y2 = y2
    face = face[cut_y1:cut_y2,cut_x1:cut_x2]
    face = resize(face, (256, 256))[..., :3]
    
    return face

# find the face in webcam stream and center a 256x256 window
def find_face_cut(net,face,previous=False):
    blob = cv2.dnn.blobFromImage(face, 1.0, (300, 300), [104, 117, 123], False, False)
    frameWidth = 640
    frameHeight = 480
    net.setInput(blob)
    detections = net.forward()
    bboxes = []
    for i in range(detections.shape[2]):
        confidence = detections[0, 0, i, 2]
        if confidence > 0.8:
            x1 = int(detections[0, 0, i, 3] * frameWidth)
            y1 = int(detections[0, 0, i, 4] * frameHeight)
            x2 = int(detections[0, 0, i, 5] * frameWidth)
            y2 = int(detections[0, 0, i, 6] * frameHeight)

            face_margin_w = int(256 - (abs(x1-x2) -.5))
            face_margin_h = int(256 - (abs(y1-y2) -.5))

            cut_x1 = (x1 - int(face_margin_w/2))
            if cut_x1<0: cut_x1=0
            cut_y1 = y1 - int(2*face_margin_h/3)
            if cut_y1<0: cut_y1=0
            cut_x2 = x2 + int(face_margin_w/2)
            cut_y2 = y2 + int(face_margin_h/3)

    if range(detections.shape[2]) == 0:
        print("face not found in video")
        exit()
    else:
        print(f'Found face at: ({x1,y1}) ({x2},{y2} width:{abs(x2-x1)} height: {abs(y2-y1)})')
        print(f'Cutting at: ({cut_x1,cut_y1}) ({cut_x2},{cut_y2} width:{abs(cut_x2-cut_x1)} height: {abs(cut_y2-cut_y1)})')


    return cut_x1,cut_y1,cut_x2,cut_y2

def readnextimage(position=-1):
    global img_list,pos
    if (position != -1):
        pos = position
    else:
        if pos<len(img_list)-1:
            pos=pos+1
        else:
            pos=0
    source_image = imageio.imread(img_list[pos])
    source_image = resize(source_image, (256, 256))[..., :3]
    return source_image

main()
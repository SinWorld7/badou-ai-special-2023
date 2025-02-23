# -*- coding:utf-8 -*-

import numpy as np
import tensorflow as tf
import os


class yolo:
    def __init__(self, norm_epsilon, norm_decay, anchors_path, classes_path, pre_train):
        # 学习率衰减
        self.norm_epsilon = norm_epsilon
        self.norm_decay = norm_decay
        self.anchors_path = anchors_path
        self.classes_path = classes_path
        self.pre_train = pre_train
        self.anchors = self.get_anchors()
        self.classes = self.get_class()

    # 获取类别
    def get_class(self):
        classes_path = os.path.expanduser(self.classes_path)
        with open(classes_path) as f:
            class_names = f.readlines()
        class_names = [c.strip() for c in class_names]
        return class_names

    # 获取目标框
    def get_anchors(self):
        anchors_path = os.path.expanduser(self.anchors_path)
        with open(anchors_path) as f:
            anchors = f.readline()
        anchors = [float(x) for x in anchors.split(',')]
        return np.array(anchors).reshape(-1, 2)

    # BN层（BN + leaky relu）
    def BN(self, input_layer, name=None, training=True, norm_decay=0.99, norm_epsilon=1e-3):

        bn_layer = tf.layers.batch_normalization(inputs=input_layer, momentum=norm_decay, epsilon=norm_epsilon, center=True,
                                                 scale=True, training=training, name=name)
        return tf.nn.leaky_relu(bn_layer, alpha=0.1)

    # 卷积层
    def conv_block(self, inputs, filters_num, kernel_size, name, use_bias=False, strides=1):

        conv = tf.layers.conv2d(inputs=inputs, filters=filters_num,
                                kernel_size=kernel_size, strides=[strides, strides],
                                kernel_initializer=tf.glorot_uniform_initializer(),
                                padding=('SAME' if strides == 1 else 'VALID'),
                                kernel_regularizer=tf.contrib.layers.l2_regularizer(scale=5e-4),
                                use_bias=use_bias, name=name)
        return conv

    # 残差块 （3x3 1x1 3x3）
    def res_block(self, inputs, filters_num, blocks_num, conv_index, training = True, norm_decay = 0.99, norm_epsilon = 1e-3):
        # 在输入feature map的长宽维度进行padding
        inputs = tf.pad(inputs, paddings=[[0, 0], [1, 0], [1, 0], [0, 0]], mode='CONSTANT')
        layer = self.conv_block(inputs, filters_num, kernel_size=3, strides=2, name="conv2d_" + str(conv_index))
        layer = self.BN(layer, name="batch_normalization_" + str(conv_index), training=training, norm_decay=norm_decay, norm_epsilon = norm_epsilon)
        conv_index += 1
        for _ in range(blocks_num):
            shortcut = layer
            layer = self.conv_block(layer, filters_num // 2, kernel_size=1, strides=1, name="conv2d_" + str(conv_index))
            layer = self.BN(layer, name="batch_normalization_" + str(conv_index), training=training, norm_decay=norm_decay, norm_epsilon=norm_epsilon)
            conv_index += 1
            layer = self.conv_block(layer, filters_num, kernel_size=3, strides=1, name="conv2d_" + str(conv_index))
            layer = self.BN(layer, name="batch_normalization_" + str(conv_index), training=training, norm_decay=norm_decay, norm_epsilon=norm_epsilon)
            conv_index += 1
            layer += shortcut
        return layer, conv_index

    #   特征提取网络darknet53
    def darknet53(self, inputs, conv_index, training=True, norm_decay=0.99, norm_epsilon=1e-3):

        with tf.variable_scope('darknet53'):
            # 416,416,3 -> 416,416,32
            conv = self.conv_block(inputs, filters_num=32, kernel_size=3, strides=1, name="conv2d_" + str(conv_index))
            conv = self.BN(conv, name="batch_normalization_" + str(conv_index), training = training, norm_decay=norm_decay, norm_epsilon=norm_epsilon)
            conv_index += 1
            # 416,416,32 -> 208,208,64
            conv, conv_index = self.res_block(conv, conv_index=conv_index, filters_num=64, blocks_num=1, training=training, norm_decay=norm_decay, norm_epsilon=norm_epsilon)
            # 208,208,64 -> 104,104,128
            conv, conv_index = self.res_block(conv, conv_index=conv_index, filters_num=128, blocks_num=2, training=training, norm_decay=norm_decay, norm_epsilon=norm_epsilon)
            # 104,104,128 -> 52,52,256
            conv, conv_index = self.res_block(conv, conv_index=conv_index, filters_num=256, blocks_num=8, training=training, norm_decay=norm_decay, norm_epsilon=norm_epsilon)
            # route1 = 52,52,256
            route1 = conv
            # 52,52,256 -> 26,26,512
            conv, conv_index = self.res_block(conv, conv_index=conv_index, filters_num=512, blocks_num=8, training=training, norm_decay=norm_decay, norm_epsilon=norm_epsilon)
            # route2 = 26,26,512
            route2 = conv
            # 26,26,512 -> 13,13,1024
            conv, conv_index = self.res_block(conv, conv_index=conv_index,  filters_num=1024, blocks_num=4, training=training, norm_decay=norm_decay, norm_epsilon=norm_epsilon)
            # route3 = 13,13,1024
        return route1, route2, conv, conv_index

    # 输出两个网络结果
    # 第一个是进行5次卷积后，用于下一次逆卷积的，卷积过程是1X1，3X3，1X1，3X3，1X1
    # 第二个是进行5+2次卷积，作为一个特征层的，卷积过程是1X1，3X3，1X1，3X3，1X1，3X3，1X1
    def yolo_block(self, inputs, filters_num, out_filters, conv_index, training = True, norm_decay = 0.99, norm_epsilon = 1e-3):

        conv = self.conv_block(inputs, filters_num=filters_num, kernel_size=1, strides=1, name="conv2d_" + str(conv_index))
        conv = self.BN(conv, name="batch_normalization_" + str(conv_index), training=training, norm_decay=norm_decay, norm_epsilon=norm_epsilon)
        conv_index += 1
        conv = self.conv_block(conv, filters_num=filters_num * 2, kernel_size=3, strides=1, name="conv2d_" + str(conv_index))
        conv = self.BN(conv, name="batch_normalization_" + str(conv_index), training=training, norm_decay=norm_decay, norm_epsilon=norm_epsilon)
        conv_index += 1
        conv = self.conv_block(conv, filters_num=filters_num, kernel_size=1, strides=1, name = "conv2d_" + str(conv_index))
        conv = self.BN(conv, name="batch_normalization_" + str(conv_index), training=training, norm_decay=norm_decay, norm_epsilon=norm_epsilon)
        conv_index += 1
        conv = self.conv_block(conv, filters_num=filters_num * 2, kernel_size=3, strides=1, name="conv2d_" + str(conv_index))
        conv = self.BN(conv, name="batch_normalization_" + str(conv_index), training=training, norm_decay=norm_decay, norm_epsilon=norm_epsilon)
        conv_index += 1
        conv = self.conv_block(conv, filters_num=filters_num, kernel_size=1, strides=1, name="conv2d_" + str(conv_index))
        conv = self.BN(conv, name="batch_normalization_" + str(conv_index), training = training, norm_decay=norm_decay, norm_epsilon=norm_epsilon)
        conv_index += 1
        route = conv
        conv = self.conv_block(conv, filters_num=filters_num * 2, kernel_size=3, strides=1, name="conv2d_" + str(conv_index))
        conv = self.BN(conv, name="batch_normalization_" + str(conv_index), training=training, norm_decay=norm_decay, norm_epsilon=norm_epsilon)
        conv_index += 1
        conv = self.conv_block(conv, filters_num=out_filters, kernel_size=1, strides=1, name="conv2d_" + str(conv_index), use_bias=True)
        conv_index += 1
        return route, conv, conv_index

    # 返回三个特征层的内容
    def yolo_inference(self, inputs, num_anchors, num_classes, training = True):

        conv_index = 1
        # route1 = 52,52,256、route2 = 26,26,512、route3 = 13,13,1024
        conv2d_26, conv2d_43, conv, conv_index = self.darknet53(inputs, conv_index, training=training, norm_decay=self.norm_decay, norm_epsilon=self.norm_epsilon)
        with tf.variable_scope('yolo'):
            # 第一个特征层
            # conv2d_57 = 13,13,512，conv2d_59 = 13,13,255(3x(80+5))
            conv2d_57, conv2d_59, conv_index = self.yolo_block(conv, 512, num_anchors * (num_classes + 5), conv_index=conv_index, training = training, norm_decay=self.norm_decay, norm_epsilon = self.norm_epsilon)

            # 第二个特征层
            conv2d_60 = self.conv_block(conv2d_57, filters_num=256, kernel_size=1, strides=1, name="conv2d_" + str(conv_index))
            conv2d_60 = self.BN(conv2d_60, name="batch_normalization_" + str(conv_index),training=training, norm_decay=self.norm_decay, norm_epsilon = self.norm_epsilon)
            conv_index += 1
            # unSample_0 = 26,26,256
            unSample_0 = tf.image.resize_nearest_neighbor(conv2d_60, [2 * tf.shape(conv2d_60)[1], 2 * tf.shape(conv2d_60)[1]], name='upSample_0')
            # route0 = 26,26,768
            route0 = tf.concat([unSample_0, conv2d_43], axis = -1, name = 'route_0')
            # conv2d_65 = 52,52,256，conv2d_67 = 26,26,255
            conv2d_65, conv2d_67, conv_index = self.yolo_block(route0, 256, num_anchors * (num_classes + 5), conv_index=conv_index, training = training, norm_decay = self.norm_decay, norm_epsilon = self.norm_epsilon)

            # 第三个特征层
            conv2d_68 = self.conv_block(conv2d_65, filters_num = 128, kernel_size=1, strides=1, name="conv2d_" + str(conv_index))
            conv2d_68 = self.BN(conv2d_68, name="batch_normalization_" + str(conv_index), training=training, norm_decay=self.norm_decay, norm_epsilon = self.norm_epsilon)
            conv_index += 1
            # unSample_1 = 52,52,128
            unSample_1 = tf.image.resize_nearest_neighbor(conv2d_68, [2 * tf.shape(conv2d_68)[1], 2 * tf.shape(conv2d_68)[1]], name='upSample_1')
            # route1= 52,52,384
            route1 = tf.concat([unSample_1, conv2d_26], axis=-1, name='route_1')
            # conv2d_75 = 52,52,255
            _, conv2d_75, _ = self.yolo_block(route1, 128, num_anchors * (num_classes + 5), conv_index=conv_index, training=training, norm_decay=self.norm_decay, norm_epsilon=self.norm_epsilon)

        return [conv2d_59, conv2d_67, conv2d_75]


__author__ = 'dudevil'

import os
import sys
import time
import numpy
import theano
import theano.tensor as T
from read_data import DataSetLoader
from optimization import gen_updates_nesterov_momentum_no_bias_decay
from layers import *


# define some parameters
learning_rate_schedule = {
    0: 0.02,
    50: 0.01,
    100: 0.001,
}

momentum_schedule = {
    0: 0.9,
    100: 0.95,
}

n_epochs = 150
nkerns = [32, 64, 128, 128]
batch_size = 200

if __name__ == "__main__":
    """
    Build train and evaluate model
    """
    rng = numpy.random.RandomState(190215)
    print "Preparing datasets ..."
    # load data and split train/test set stratified by classes
    dsl = DataSetLoader(rng=rng, img_size=48, n_epochs=n_epochs, parallel=True, pad=True)
    train_gen = dsl.train_gen(augment=True)
    valid_gen = dsl.valid_gen()
    train_x, train_y = train_gen.next()
    valid_x, valid_y = valid_gen.next()
    # test_x = dsl.load_test()
    # compute number of minibatches for training, validation and testing
    n_train_batches = train_x.shape[0] / batch_size
    n_val_batches = valid_x.shape[0] / batch_size
    # n_test_batches = test_x.shape[0] / batch_size

    train_x = theano.shared(train_x, borrow=True)
    valid_x = theano.shared(valid_x, borrow=True)
    # won't fit into my gpu memory

    train_y = T.cast(theano.shared(train_y, borrow=True), dtype='int32')
    valid_y = T.cast(theano.shared(valid_y, borrow=True), dtype='int32')

    # allocate learning rate and momentum shared variables
    learning_rate = theano.shared(numpy.array(learning_rate_schedule[0], dtype=theano.config.floatX))
    momentum = theano.shared(numpy.array(momentum_schedule[0], dtype=theano.config.floatX))

    # allocate symbolic variables for the data
    index = T.lscalar()  # index to a [mini]batch
    x = T.matrix('x')   # the data is presented as rasterized images
    y = T.ivector('y')  # the labels are presented as 1D vector of [int] labels
    dropout_active = T.bscalar('dropout_active')  # a flag to enable and disable dropout

    ######################
    # BUILD ACTUAL MODEL #
    ######################
    print 'Building the model ...'

    # Reshape matrix of rasterized images of shape (batch_size, 48 * 48)
    # to a 4D tensor, compatible with our ConvPoolLayer
    #layer0_input = x.reshape((batch_size, 1, 49, 49))
    #slice = SliceLayer(x.reshape((batch_size, 1, 64, 64)), (batch_size, 1, 64, 64))
    #new_batch_size = batch_size * slice.n_parts
    # Construct the first convolutional pooling layer:
    # filtering reduces the image size to ((48-5)+1 , (48-5)+1) = (44, 44)
    # maxpooling reduces this further to (44/2, 44/2) = (22, 22)
    # 4D output tensor is thus of shape (batch_size, nkerns[0], 22, 22)
    layer0 = ConvPoolLayer(
        rng,
        input=x.reshape((batch_size, 1, 48, 48)),
        image_shape=(batch_size, 1, 48, 48),
        filter_shape=(nkerns[0], 1, 5, 5),
        poolsize=(2, 2),
        normalize=True,
        activation=None
    )

    prlayer0 = ParametrizedReLuLayer(layer0.output)

    # Construct the second convolutional pooling layer
    # filtering reduces the image size to (22-5+1, 22-5+1) = (18, 18)
    # maxpooling reduces this further to (18/2, 18/2) = (9, 9)
    # 4D output tensor is thus of shape (batch_size, nkerns[1], 14, 14)
    #layer1_input = dropout(rng, layer0.output, (batch_size, nkerns[0], 22, 22), dropout_active, rate=0.1)
    #layer1_input = prlayer.output
    layer1 = ConvPoolLayer(
        rng,
        input=prlayer0.output,
        image_shape=(batch_size, nkerns[0], 22, 22),
        filter_shape=(nkerns[1], nkerns[0], 5, 5),
        poolsize=(2, 2),
        normalize=True,
        activation=None
    )

    prlayer1 = ParametrizedReLuLayer(layer1.output)
    # Construct the second convolutional pooling layer
    # filtering reduces the image size to (9-4+1, 9-4+1) = (6, 6)
    #layer2_input = dropout(rng, layer1.output, (batch_size, nkerns[1], 9, 9), dropout_active, rate=0.1)
    #dout5 = DropOutLayer(rng, layer1.output, (batch_size, nkerns[1], 9, 9), dropout_active, rate=0.9)

    layer2_input = prlayer1.output
    layer2 = ConvPoolLayer(
        rng,
        input=layer2_input,
        image_shape=(batch_size, nkerns[1], 9, 9),
        filter_shape=(nkerns[2], nkerns[1], 4, 4),
        poolsize=(),
        activation=None
    )

    # Construct the second convolutional pooling layer
    # filtering reduces the image size to (6-3+1, 6-3+1) = (4, 4)
    # maxpooling reduces this further to (4/2, 4/2) = (2, 2)
    prlayer2 = ParametrizedReLuLayer(layer2.output)
    #dout4 = DropOutLayer(rng, layer2.output, (batch_size, nkerns[2], 6, 6), dropout_active, rate=0.9)

    layer7 = ConvPoolLayer(
        rng,
        input=prlayer2.output,
        image_shape=(batch_size, nkerns[2], 6, 6),
        filter_shape=(nkerns[3], nkerns[2], 3, 3),
        poolsize=(2, 2),
        activation=None
    )

    prlayer3 = ParametrizedReLuLayer(layer7.output)
    # the HiddenLayer being fully-connected, it operates on 2D matrices of
    # shape (batch_size, num_pixels) (i.e matrix of rasterized images).
    # This will generate a matrix of shape (batch_size, nkerns[2] * 5 * 5),
    #merge = MergeLayer(layer7.output, (new_batch_size, 1, nkerns[3], 2, 2), slice.n_parts)
    dout1 = DropOutLayer(rng, prlayer3.output.flatten(2), (batch_size, nkerns[3] * 2 * 2), dropout_active)
    # construct a fully-connected relu layer
    layer3 = HiddenLayer(
        rng,
        input=dout1.output,
        n_in=dout1.output_shape[1],
        n_out=1024,
        activation=None,
        max_col_norm=0
    )
    prlayer4 = ParametrizedReLuLayer(layer3.output)
    # Maxout layer reduces output dimension to (batch_size, input_dim / pool_size)
    # in this case: (batch_size, 512/2) = (batch_size, 256)
    # maxlayer1 = MaxOutLayer(
    #     input=layer3.output,
    #     input_shape=(batch_size, 1024),
    #     pool_size=2
    # )
    # add dropout at 0.5 rate
    dout2 = DropOutLayer(rng, prlayer4.output, (batch_size, 1024), dropout_active)
    # Maxout layer reduces output dimension to (batch_size, input_dim / pool_size)
    # in this case: (batch_size, 512/2) = (batch_size, 256)
    # one more fully-connected relu layer
    layer4 = HiddenLayer(
        rng,
        input=dout2.output,
        n_in=1024,
        n_out=1024,
        activation=None,
        max_col_norm=0
    )
    # Maxout layer reduces output dimension to (batch_size, input_dim / pool_size)
    # in this case: (batch_size, 2048/2) = (batch_size, 1024)
    # maxlayer2 = MaxOutLayer(
    #     input=layer4.output,
    #     input_shape=(batch_size, 1024),
    #     pool_size=2
    # )
    prlayer5 = ParametrizedReLuLayer(layer4.output)
    # add dropout at 0.5 rate
    dout3 = DropOutLayer(rng, prlayer5.output, (batch_size, 1024), dropout_active)
    # classify the values of the fully-connected sigmoidal layer
    layer6 = LogisticRegression(input=dout3.output, n_in=1024, n_out=121)

    # the cost we minimize during training is the NLL of the model
    cost = layer6.negative_log_likelihood(y)

    # create a function to compute the mistakes that are made by the model
    # this is basically a fraction of incorrectly classified images
    test_model = theano.function(
        [index],
        layer6.errors(y),
        givens={
            x: valid_x[index * batch_size: (index + 1) * batch_size],
            y: valid_y[index * batch_size: (index + 1) * batch_size],
            dropout_active: theano.shared(numpy.array(0, dtype='int8'), borrow=False)
        }
    )

    # create a function to compute the multi-class logarithmic loss which is the evaluation metric
    # for this competition (it's the same as negative loglikelyhood)
    test_logloss = theano.function(
        [index],
        layer6.negative_log_likelihood(y),
        givens={
            x: valid_x[index * batch_size: (index + 1) * batch_size],
            y: valid_y[index * batch_size: (index + 1) * batch_size],
            dropout_active: theano.shared(numpy.array(0, dtype='int8'), borrow=False)
        }
    )

    # create a list of all model parameters to be fit by gradient descent
    params = layer6.params + layer4.params + layer2.params + layer1.params + layer0.params +\
             layer3.params + layer7.params

    # a list of bias parameters: these will be excluded from the Nesterov momentum updates
    bias_params = layer6.bias_params + layer4.bias_params + layer2.bias_params + layer1.bias_params \
                  + layer0.bias_params + layer3.bias_params + layer7.bias_params + prlayer5.params + \
                  prlayer4.params + prlayer3.params + prlayer2.params + prlayer1.params + prlayer0.params

    # we generate the updates to the parameters with Nesterov momentum
    updates = gen_updates_nesterov_momentum_no_bias_decay(cost, params,
                                                          bias_params,
                                                          learning_rate=learning_rate,
                                                          momentum=momentum)

    # apply max-norm regularization
    layer3.censor_updates(updates)
    layer4.censor_updates(updates)

    # create a function to train the neural network
    train_model = theano.function(
        [index],
        cost,
        updates=updates,
        givens={
            x: train_x[index * batch_size: (index + 1) * batch_size],
            y: train_y[index * batch_size: (index + 1) * batch_size],
            dropout_active: theano.shared(numpy.array(1, dtype='int8'), borrow=False),
        }
    )

    # save train and validation errors for future analysis
    valid_err = []
    test_err = []
    n_iter = []
    a0 = []
    a1 = []
    a2 = []
    a3 = []
    a4 = []
    a5 = []
    ###############
    # TRAIN MODEL #
    ###############
    print 'Training ...'
    # early-stopping parameters
    patience = 10000  # look as this many examples regardless
    patience_increase = 2  # wait this much longer when a new best is
                           # found
    improvement_threshold = 0.995  # a relative improvement of this much is
                                   # considered significant
    validation_frequency = min(n_train_batches, patience / 2)
                                  # go through this many
                                  # minibatche before checking the network
                                  # on the validation set; in this case we
                                  # check every epoch

    best_test_logloss = numpy.inf
    best_iter = 0
    test_score = 0.
    start_time = time.clock()

    epoch = 0
    done_looping = False
    print("| Epoch | Train err | Validation err | Validation misclass | Ratio |")
    print("|------------------------------------------------------------------|")
    while (epoch < n_epochs) and (not done_looping):
        epoch = epoch + 1
        for minibatch_index in xrange(n_train_batches):

            iter = (epoch - 1) * n_train_batches + minibatch_index

            # if iter % 100 == 0:
            #     print 'training @ iter = ', iter
            cost_ij = train_model(minibatch_index)

            # update learning rate and momentum according to schedule
            if epoch in learning_rate_schedule:
                 learning_rate.set_value(numpy.array(learning_rate_schedule[epoch], dtype=theano.config.floatX))
            if epoch in momentum_schedule:
                 momentum.set_value(numpy.array(momentum_schedule[epoch], dtype=theano.config.floatX))

            if (iter + 1) % validation_frequency == 0:

                # compute zero-one loss on validation set
                test_losses = [test_model(i) for i
                                     in xrange(n_val_batches)]
                test_loglosses = [test_logloss(i) for i
                                     in xrange(n_val_batches)]
                this_test_loss = numpy.mean(test_losses)
                this_test_logloss = numpy.mean(test_loglosses)
                print("|%6d | %9.6f | %14.6f | %17.2f %% | %1.3f |" %
                      (epoch, cost_ij, this_test_logloss, this_test_loss * 100., this_test_logloss / cost_ij))
                # print('epoch %i, minibatch %i/%i, validation error %.2f %% loglikelihood %f train error %f' %
                #       (epoch, minibatch_index + 1, n_train_batches,
                #        this_test_loss * 100., this_test_logloss, cost_ij))
                # print('Max weight in dense layers 1: %f 2: %f' %
                #       (numpy.mean(numpy.sqrt(numpy.sum(numpy.square(layer3.W.get_value(borrow=True)), axis=0))),
                #        numpy.mean(numpy.sqrt(numpy.sum(numpy.square(layer4.W.get_value(borrow=True)), axis=0)))))
                #
                # save for later analysis
                valid_err.append(cost_ij)
                test_err.append(this_test_logloss)
                n_iter.append(epoch)
                a0.append(prlayer0.a.get_value())
                a1.append(prlayer1.a.get_value())
                a2.append(prlayer2.a.get_value())
                a3.append(prlayer3.a.get_value())
                a4.append(prlayer4.a.get_value())
                a5.append(prlayer5.a.get_value())
                # if we got the best validation score until now
                if this_test_logloss < best_test_logloss:

                    #improve patience if loss improvement is good enough
                    if this_test_logloss < best_test_logloss *  \
                       improvement_threshold:
                        patience = max(patience, iter * patience_increase)

                    # save best validation score and iteration number
                    best_test_logloss = this_test_logloss
                    best_test_loss = this_test_loss
                    best_iter = iter
            # if epoch % 100 == 0:
            #
            #     numpy.save("data/tidy/%d_layer0.npy" % epoch, layer0.W.get_value(borrow=True))
            #     numpy.save("data/tidy/%d_layer3.npy" % epoch, layer3.W.get_value(borrow=True))
            #     numpy.save("data/tidy/%d_layer4.npy" % epoch, layer4.W.get_value(borrow=True))
            #     numpy.save("data/tidy/%d_layer6.npy" % epoch, layer6.W.get_value(borrow=True))
            if patience <= iter:
                done_looping = True
                break
        #print("[%f] epoch done" % time.clock())
        # get training data for next epoch
        nx, ny = train_gen.next()
        #print("[%f] train epoch generated" % time.clock())
        # load the data into the GPU
        train_x.set_value(nx, borrow=True)
        train_y.set_value(ny, borrow=True)
        #print("[%f] train epoch loaded" % time.clock())

    end_time = time.clock()
    print('Optimization complete.')
    print('Best logloss score of %f %% obtained at iteration %i (epoch %i), '
          'with misclassification rate %f %%' %
          (best_test_logloss, best_iter + 1, best_iter / n_train_batches + 1, best_test_loss * 100.))
    print >> sys.stderr, ('The training lasted %.2fm' % ((end_time - start_time) / 60.))
    ################
    #  Predicting  #
    ################
    # res = []
    # print(test_x.shape)
    #
    # n_test_batches = test_x.shape[0] / batch_size
    # test_x = theano.shared(test_x, borrow=True)
    #
    # predict = theano.function(
    #     [index],
    #     layer6.predict_proba(),
    #     givens={
    #         x: test_x[index * batch_size: (index + 1) * batch_size],
    #         dropout_active: theano.shared(numpy.array(0, dtype='int8'), borrow=False)
    #         },
    # )
    # for minibatch_index in xrange(n_test_batches):
    #         tmp = predict(minibatch_index)
    #         res.append(tmp)
    # result = numpy.vstack(tuple(res))
    # print(result.shape)
    # dsl.save_submission(result, '2')

    # save train and validation errors
    results = numpy.array([n_iter, test_err, valid_err], dtype=numpy.float)
    numpy.save("data/tidy/49_4cl_prelu2048_rotations.npy", results)
    a = numpy.array([n_iter, a0, a1, a2, a3, a4, a5], dtype=numpy.float)
    numpy.save("data/tidy/as.npy", a)


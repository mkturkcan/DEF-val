
""" 
MIT License

Copyright (c) 2018 Mehmet Kerem Turkcan

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE. 
"""
# ============================================================================
# Copyright 2018 The TensorFlow Probability Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ============================================================================

# Based on https://github.com/tensorflow/probability/blob/master/tensorflow_probability/examples/deep_exponential_family.py


"""Trains a sparse Gamma deep exponential family on NIPS 2011 conference papers.
We apply a sparse Gamma deep exponential family [3] as a topic model on the
collection of NIPS 2011 conference papers [2]. Note that [3] applies score
function gradients with advanced variance reduction techniques; instead we apply
implicit reparameterization gradients [1]. Preliminary experiments for this
model and task suggest that implicit reparameterization exhibits lower gradient
variance and trains faster.
With default flags, fitting the model takes ~60s for 10,000 steps on a GTX
1080 Ti. The following results are after 120,000 steps.
Topic 0: let distribution set strategy distributions given learning
        information use property
Topic 1: functions problem risk function submodular cut level
        clustering sets performance
Topic 2: action value learning regret reward actions algorithm optimal
        state return
Topic 3: posterior stochastic approach information based using prior
        mean divergence since
Topic 4: player inference game propagation experts static query expert
        base variables
Topic 5: algorithm set loss weak algorithms optimal submodular online
        cost setting
Topic 6: sparse sparsity norm solution learning penalty greedy
        structure wise regularization
Topic 7: learning training linear kernel using coding accuracy
        performance dataset based
Topic 8: object categories image features examples classes images
        class objects visual
Topic 9: data manifold matrix points dimensional point low linear
        gradient optimization
#### References
[1]: Michael Figurnov, Shakir Mohamed, Andriy Mnih. Implicit Reparameterization
         Gradients, 2018.
         https://arxiv.org/abs/1805.08498.
[2]: Valerio Perrone and Paul A Jenkins and Dario Spano and Yee Whye Teh.
         Poisson Random Fields for Dynamic Feature Models, 2016.
         https://arxiv.org/abs/1611.07460
[3]: Rajesh Ranganath, Linpeng Tang, Laurent Charlin, David M. Blei. Deep
         Exponential Families. In _Artificial Intelligence and Statistics_, 2015.
         https://arxiv.org/abs/1411.2581
"""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import csv
import os
import time

# Dependency imports
from absl import flags
import numpy as np
from six.moves import urllib
import tensorflow as tf

from tensorflow_probability import edward2 as ed

flags.DEFINE_float("learning_rate",
                                     default=1e-4,
                                     help="Initial learning rate.")
flags.DEFINE_integer("max_steps",
                                         default=200000,
                                         help="Number of training steps to run.")
flags.DEFINE_list("layer_sizes",
                                    default=["100", "30", "15"],
                                    help="Comma-separated list denoting number of latent "
                                             "variables (stochastic units) per layer.")
flags.DEFINE_float("shape",
                                     default=0.1,
                                     help="Shape hyperparameter for Gamma priors on latents.")
flags.DEFINE_string("data_dir",
                                        default=os.path.join(os.getenv("TEST_TMPDIR", "/tmp"),
                                                                                 "deep_exponential_family/data"),
                                        help="Directory where data is stored (if using real data).")
flags.DEFINE_string("model_dir",
                                        default=os.path.join(os.getenv("TEST_TMPDIR", "/tmp"),
                                                                                 "deep_exponential_family/"),
                                        help="Directory to put the model's fit.")
flags.DEFINE_bool("fake_data",
                                    default=None,
                                    help="If true, uses fake data. Defaults to real data.")

FLAGS = flags.FLAGS


def deep_exponential_family(data_size, feature_size, units, shape):
    """A multi-layered topic model over a documents-by-terms matrix."""
    w2 = ed.Gamma(0.1, 0.3, sample_shape=[units[2], units[1]], name="w2")
    w1 = ed.Gamma(0.1, 0.3, sample_shape=[units[1], units[0]], name="w1")
    w0 = ed.Gamma(0.1, 0.3, sample_shape=[units[0], feature_size], name="w0")

    z2 = ed.Gamma(0.1, 0.1, sample_shape=[data_size, units[2]], name="z2")
    z1 = ed.Gamma(shape, shape / tf.matmul(z2, w2), name="z1")
    z0 = ed.Gamma(shape, shape / tf.matmul(z1, w1), name="z0")
    x = ed.Poisson(tf.matmul(z0, w0), name="x")
    return x


def trainable_positive_deterministic(shape, min_loc=1e-3, name=None):
    """Learnable Deterministic distribution over positive reals."""
    with tf.variable_scope(None, default_name="trainable_positive_deterministic"):
        unconstrained_loc = tf.get_variable("unconstrained_loc", shape)
        loc = tf.maximum(tf.nn.softplus(unconstrained_loc), min_loc)
        rv = ed.Deterministic(loc=loc, name=name)
        return rv


def trainable_gamma(shape, min_concentration=1e-3, min_scale=1e-5, name=None):
    """Learnable Gamma via concentration and scale parameterization."""
    with tf.variable_scope(None, default_name="trainable_gamma"):
        unconstrained_concentration = tf.get_variable(
                "unconstrained_concentration", shape,
                initializer=tf.random_normal_initializer(mean=0.5, stddev=0.1))
        unconstrained_scale = tf.get_variable(
                "unconstrained_scale", shape,
                initializer=tf.random_normal_initializer(stddev=0.1))
        concentration = tf.maximum(tf.nn.softplus(unconstrained_concentration),
                                                             min_concentration)
        rate = tf.maximum(1. / tf.nn.softplus(unconstrained_scale), 1. / min_scale)
        rv = ed.Gamma(concentration=concentration, rate=rate, name=name)
        return rv


def deep_exponential_family_variational(data_size, feature_size, units):
    """Posterior approx. for deep exponential family p(w{0,1,2}, z{1,2,3} | x)."""
    qw2 = trainable_positive_deterministic([units[2], units[1]], name="qw2")
    qw1 = trainable_positive_deterministic([units[1], units[0]], name="qw1")
    qw0 = trainable_positive_deterministic([units[0], feature_size], name="qw0")
    qz2 = trainable_gamma([data_size, units[2]], name="qz2")
    qz1 = trainable_gamma([data_size, units[1]], name="qz1")
    qz0 = trainable_gamma([data_size, units[0]], name="qz0")
    return qw2, qw1, qw0, qz2, qz1, qz0


def make_value_setter(**model_kwargs):
    """Creates a value-setting interceptor.
    Args:
        **model_kwargs: dict of str to Tensor. Keys are the names of random variable
            in the model to which this interceptor is being applied. Values are
            Tensors to set their value to.
    Returns:
        set_values: Function which sets the value of intercepted ops.
    """
    def set_values(f, *args, **kwargs):
        """Sets random variable values to its aligned value."""
        name = kwargs.get("name")
        if name in model_kwargs:
            kwargs["value"] = model_kwargs[name]
        return ed.interceptable(f)(*args, **kwargs)
    return set_values


def load_nips2011_papers(path):
    """Loads NIPS 2011 conference papers.
    The NIPS 1987-2015 data set is in the form of a 11,463 x 5,812 matrix of
    per-paper word counts, containing 11,463 words and 5,811 NIPS conference
    papers (Perrone et al., 2016). We subset to papers in 2011 and words appearing
    in at least two documents and having a total word count of at least 10.
    Built from the Observations Python package.
    Args:
        path: str.
            Path to directory which either stores file or otherwise file will
            be downloaded and extracted there. Filename is `NIPS_1987-2015.csv`.
    Returns:
        bag_of_words: np.ndarray of shape [num_documents, num_words]. Each element
            denotes the number of occurrences of a specific word in a specific
            document.
        words: List of strings, denoting the words for `bag_of_words`'s columns.
    """
    path = os.path.expanduser(path)
    filename = "NIPS_1987-2015.csv"
    filepath = os.path.join(path, filename)
    if not os.path.exists(filepath):
        url = ("https://archive.ics.uci.edu/ml/machine-learning-databases/"
                     "00371/NIPS_1987-2015.csv")
        if not tf.gfile.Exists(path):
            tf.gfile.MakeDirs(path)
        print("Downloading %s to %s" % (url, filepath))
        urllib.request.urlretrieve(url, filepath)

    with open(filepath) as f:
        iterator = csv.reader(f)
        documents = next(iterator)[1:]
        words = []
        x_train = []
        for row in iterator:
            words.append(row[0])
            x_train.append(row[1:])

    x_train = np.array(x_train, dtype=np.int)
    doc_idx = [i for i, document in enumerate(documents)]
    documents = [documents[doc] for doc in doc_idx]
    x_train = x_train[:, doc_idx]
    word_idx = np.logical_and(np.sum(x_train != 0, 1) >= 2,
                                                        np.sum(x_train, 1) >= 10)
    words = [word for word, idx in zip(words, word_idx) if idx]
    bag_of_words = x_train[word_idx, :].T
    return bag_of_words, words


def main(argv):
    del argv  # unused
    FLAGS.layer_sizes = [int(layer_size) for layer_size in FLAGS.layer_sizes]
    if len(FLAGS.layer_sizes) != 3:
        raise NotImplementedError("Specifying fewer or more than 3 layers is not "
                                                            "currently available.")
    if tf.gfile.Exists(FLAGS.model_dir):
        tf.logging.warning(
                "Warning: deleting old log directory at {}".format(FLAGS.model_dir))
        tf.gfile.DeleteRecursively(FLAGS.model_dir)
    tf.gfile.MakeDirs(FLAGS.model_dir)

    if FLAGS.fake_data:
        bag_of_words = np.random.poisson(1., size=[10, 25])
        words = [str(i) for i in range(25)]
    else:
        bag_of_words, words = load_nips2011_papers(FLAGS.data_dir)

    bag_of_words_val = bag_of_words[5000:]
    bag_of_words = bag_of_words[:5000]
    total_count = np.sum(bag_of_words)
    total_count_val = np.sum(bag_of_words_val)
    bag_of_words = tf.to_float(bag_of_words)
    bag_of_words_val = tf.to_float(bag_of_words_val)
    data_size, feature_size = bag_of_words.shape
    data_size_val, feature_size_val = bag_of_words_val.shape
    print('Training Shape: ', bag_of_words.shape)
    print('Validation Shape: ', bag_of_words_val.shape)


    # Compute expected log-likelihood. First, sample from the variational
    # distribution; second, compute the log-likelihood given the sample.
    qw2, qw1, qw0, qz2, qz1, qz0 = deep_exponential_family_variational(
            data_size,
            feature_size,
            FLAGS.layer_sizes)
    
    qw2_val, qw1_val, qw0_val, qz2_val, qz1_val, qz0_val = deep_exponential_family_variational(
            data_size_val,
            feature_size,
            FLAGS.layer_sizes)


    with ed.tape() as model_tape:
        with ed.interception(make_value_setter(w2=qw2, w1=qw1, w0=qw0,z2=qz2, z1=qz1, z0=qz0)):
            posterior_predictive = deep_exponential_family(data_size,
                                                             feature_size,
                                                             FLAGS.layer_sizes,
                                                             FLAGS.shape)
            
    with ed.tape() as model_tape_val:
        with ed.interception(make_value_setter(w2=qw2, w1=qw1, w0=qw0,z2=qz2_val, z1=qz1_val, z0=qz0_val)):
            posterior_predictive_val = deep_exponential_family(data_size_val,
                                                             feature_size,
                                                             FLAGS.layer_sizes,
                                                             FLAGS.shape)

    log_likelihood = posterior_predictive.distribution.log_prob(bag_of_words)
    log_likelihood = tf.reduce_sum(log_likelihood)
    tf.summary.scalar("log_likelihood", log_likelihood)
    
    log_likelihood_val = posterior_predictive_val.distribution.log_prob(bag_of_words_val)
    log_likelihood_val = tf.reduce_sum(log_likelihood_val)
    tf.summary.scalar("log_likelihood", log_likelihood_val)

    # Compute analytic KL-divergence between variational and prior distributions.
    kl = 0.
    for rv_name, variational_rv in [("z0", qz0), ("z1", qz1), ("z2", qz2),("w0", qw0), ("w1", qw1), ("w2", qw2)]:
        kl += tf.reduce_sum(variational_rv.distribution.kl_divergence(
                model_tape[rv_name].distribution))
        
    kl_val = 0.
    for rv_name, variational_rv in [("z0", qz0_val), ("z1", qz1_val), ("z2", qz2_val),("w0", qw0), ("w1", qw1), ("w2", qw2)]:
        kl_val += tf.reduce_sum(variational_rv.distribution.kl_divergence(
                model_tape_val[rv_name].distribution))

    tf.summary.scalar("kl", kl)
    tf.summary.scalar("kl_val", kl_val)

    elbo = log_likelihood - kl
    tf.summary.scalar("elbo", elbo)
    
    elbo_val = log_likelihood_val - kl_val
    tf.summary.scalar("elbo", elbo_val)
    
    optimizer = tf.train.AdamOptimizer(FLAGS.learning_rate)
    train_op = optimizer.minimize(-elbo)

    sess = tf.Session()
    summary = tf.summary.merge_all()
    summary_writer = tf.summary.FileWriter(FLAGS.model_dir, sess.graph)
    start_time = time.time()

    sess.run(tf.global_variables_initializer())
    for step in range(FLAGS.max_steps):
        start_time = time.time()
        _, elbo_value = sess.run([train_op, elbo])
        elbo_val_value = sess.run(elbo_val)
        if step % 500 == 0:
            duration = time.time() - start_time
            print("Step: {:>3d} Loss: {:.3f} ({:.3f} sec)".format(
                    step, elbo_value, duration))
            summary_str = sess.run(summary)
            summary_writer.add_summary(summary_str, step)
            summary_writer.flush()

            # Compute perplexity of the full data set. The model's negative
            # log-likelihood of data is upper bounded by the variational objective.
            negative_log_likelihood = -elbo_value
            perplexity = np.exp(negative_log_likelihood / total_count)
            
            negative_log_likelihood_val = -elbo_val_value
            perplexity_val = np.exp(negative_log_likelihood_val / total_count_val)
            
            print("Negative log-likelihood <= {:0.3f}".format(
                    negative_log_likelihood))
            print("Perplexity <= {:0.3f}".format(perplexity))
            
            print("Negative log-likelihood Val: <= {:0.3f}".format(
                    negative_log_likelihood_val))
            print("Perplexity Val <= {:0.3f}".format(perplexity_val))

            # Print top 10 words for first 10 topics.
            qw0_values = sess.run(qw0)
            for k in range(min(10, FLAGS.layer_sizes[-1])):
                top_words_idx = qw0_values[k, :].argsort()[-10:][::-1]
                top_words = " ".join([words[i] for i in top_words_idx])
                print("Topic {}: {}".format(k, top_words))

if __name__ == "__main__":
    tf.app.run()
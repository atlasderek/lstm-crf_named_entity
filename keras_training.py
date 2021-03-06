import numpy as np
from keras.preprocessing import sequence
from keras.models import Model, Sequential, model_from_json
from keras.layers.wrappers import Bidirectional
from keras.layers import Activation, Merge, average, concatenate, Input, TimeDistributed, LSTM, Dense, Dropout, Embedding
from keras.models import save_model, load_model
from keras_contrib.layers import CRF
from keras_contrib.utils import save_load_utils

from gensim.models import Word2Vec
from embedding import create_embeddings, load_vocab, tokenize

# params
MAX_LENGTH = 30
MAX_VOCAB = 25000    # see preprocessing.ipynb
TAG_VOCAB = 42
NER_VOCAB = 17
EMBEDDING_SIZE = 100 # from default gensim model, see preprocessing.ipynb
HIDDEN_SIZE = 200       # LSTM Nodes/Features/Dimension
BATCH_SIZE = 64
DROPOUTRATE = 0.2
MAX_EPOCHS = 4 # max iterations, early stop condition below

# load data
print("loading data...\n")
vocab = list(np.load('data/vocab.npy'))
sentence_text = list(np.load('data/sentence_text.npy'))
sentence_post = list(np.load('data/sentence_post.npy'))
sentence_ners = list(np.load('data/sentence_ners.npy'))
sentence_text_idx = np.load('data/sentence_text_idx.npy')
sentence_post_idx = np.load('data/sentence_post_idx.npy')
sentence_ners_idx = np.load('data/sentence_ners_idx.npy')
word2idx = np.load('data/word2idx.npy').item()
idx2word = np.load('data/idx2word.npy').item()
pos2idx = np.load('data/pos2idx.npy').item()
idx2pos = np.load('data/idx2pos.npy').item()
ner2idx = np.load('data/ner2idx.npy').item()
idx2ner = np.load('data/idx2ner.npy').item()
train_idx = np.load('data/train_idx.npy')
test_idx = np.load('data/test_idx.npy')
X_train_sents = np.load('data/X_train_sents.npy')
X_test_sents = np.load('data/X_test_sents.npy')
X_train_pos = np.load('data/X_train_pos.npy')
X_test_pos = np.load('data/X_test_pos.npy')
y_train_ner = np.load('data/y_train_ner.npy')
y_test_ner = np.load('data/y_test_ner.npy')
# load embedding data
w2v_vocab, _ = load_vocab('embeddings/text_mapping.json')
w2v_model = Word2Vec.load('embeddings/text_embeddings.gensimmodel')
w2v_pvocab, _ = load_vocab('embeddings/pos_mapping.json')
w2v_pmodel = Word2Vec.load('embeddings/pos_embeddings.gensimmodel')

# pad data
print("zero-padding sequences...\n")
X_train_sents = sequence.pad_sequences(X_train_sents, maxlen=MAX_LENGTH, truncating='post', padding='post')
X_test_sents = sequence.pad_sequences(X_test_sents, maxlen=MAX_LENGTH, truncating='post', padding='post')
X_train_pos = sequence.pad_sequences(X_train_pos, maxlen=MAX_LENGTH, truncating='post', padding='post')
X_test_pos = sequence.pad_sequences(X_test_pos, maxlen=MAX_LENGTH, truncating='post', padding='post')
y_train_ner = sequence.pad_sequences(y_train_ner, maxlen=MAX_LENGTH, truncating='post', padding='post')
y_test_ner = sequence.pad_sequences(y_test_ner, maxlen=MAX_LENGTH, truncating='post', padding='post')

TAG_VOCAB = len(list(idx2pos.keys()))
NER_VOCAB = len(list(idx2ner.keys()))

# reshape data for CRF
y_train_ner = y_train_ner[:, :, np.newaxis]
y_test_ner = y_test_ner[:, :, np.newaxis]

print(y_train_ner[:3])

# embedding matrices
print("creating embedding matrices...\n")

word_embedding_matrix = np.zeros((MAX_VOCAB, EMBEDDING_SIZE))

for word in word2idx.keys():
    # get the word vector from the embedding model
    # if it's there (check against vocab list)
    if word in w2v_vocab:
        # get the word vector
        word_vector = w2v_model[word]
        # slot it in at the proper index
word_embedding_matrix[word2idx[word]] = word_vector

pos_embedding_matrix = np.zeros((TAG_VOCAB, EMBEDDING_SIZE))

for word in pos2idx.keys():
    # get the word vector from the embedding model
    # if it's there (check against vocab list)
    if word in w2v_pvocab:
        # get the word vector
        word_vector = w2v_pmodel[word]
        # slot it in at the proper index
pos_embedding_matrix[pos2idx[word]] = word_vector

# model
print('Building model...\n')

# text layers : dense embedding > dropout > bi-LSTM
txt_input = Input(shape=(MAX_LENGTH,), name='txt_input')
txt_embed = Embedding(MAX_VOCAB, EMBEDDING_SIZE, input_length=MAX_LENGTH,
                      weights=[word_embedding_matrix],
                      name='txt_embedding', trainable=True)(txt_input)
txt_drpot = Dropout(DROPOUTRATE, name='txt_dropout')(txt_embed)
txt_lstml = Bidirectional(LSTM(HIDDEN_SIZE, return_sequences=True),
                          name='txt_bidirectional')(txt_drpot)

# pos layers : dense embedding > dropout > bi-LSTM
pos_input = Input(shape=(MAX_LENGTH,), name='pos_input')
pos_embed = Embedding(TAG_VOCAB, EMBEDDING_SIZE, input_length=MAX_LENGTH,
                      weights=[pos_embedding_matrix],
                      name='pos_embedding', trainable=True)(pos_input)
pos_drpot = Dropout(DROPOUTRATE, name='pos_dropout')(pos_embed)
pos_lstml = Bidirectional(LSTM(HIDDEN_SIZE, return_sequences=True),
                          name='pos_bidirectional')(pos_drpot)

# merged layers : merge (concat, average...) word and pos > bi-LSTM > bi-LSTM
# mrg_cncat = average([txt_lstml, pos_lstml])
mrg_cncat = concatenate([txt_lstml, pos_lstml], axis=2)
mrg_lstml = Bidirectional(LSTM(HIDDEN_SIZE, return_sequences=True),
                          name='mrg_bidirectional_1')(mrg_cncat)
# mrg_drpot = Dropout(DROPOUTRATE, name='mrg_dropout')(mrg_lstml)
mrg_lstml = Bidirectional(LSTM(HIDDEN_SIZE, return_sequences=True),
                          name='mrg_bidirectional_2')(mrg_lstml)
# mrg_outpt = Activation('sigmoid', name='mrg_activation')(mrg_lstml)

# final linear chain CRF layer
crf = CRF(NER_VOCAB, sparse_target=True)
mrg_chain = crf(mrg_lstml)

model = Model(inputs=[txt_input, pos_input], outputs=mrg_chain)

model.compile(optimizer='adam',
              loss=crf.loss_function,
              metrics=[crf.accuracy])

model.summary()

history = model.fit([X_train_sents, X_train_pos], y_train_ner,
                    validation_data=([X_test_sents, X_test_pos], y_test_ner),
                    batch_size=BATCH_SIZE,
                    epochs=MAX_EPOCHS)

hist_dict = history.history

# model.save('model/crf_model.h5')
save_load_utils.save_all_weights(model, 'model/crf_model.h5')
np.save('model/hist_dict.npy', hist_dict)
print("models saved!\n")

scores = model.evaluate([X_test_sents, X_test_pos], y_test_ner)
print('')
print('Eval model...')
print("Accuracy: %.2f%%" % (scores[1] * 100), '\n')

# CRF: https://github.com/farizrahman4u/keras-contrib/blob/master/keras_contrib/layers/crf.py
# loading keras-contrib: https://github.com/farizrahman4u/keras-contrib/issues/125
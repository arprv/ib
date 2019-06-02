BUMP_LIMIT = 20
THREAD_LIMIT = 5
SQL_CONST_OP = 0
MAX_FILE_SIZE = 1 << 21 # 2 MB
MAX_OP_IMG_WH = 250
MAX_IMG_WH = 150
ALLOWED_EXTENSIONS = set(['png', 'jpg', 'jpeg', 'gif', 'tiff', 'bmp'])
MAX_POST_LEN = 5000

class FlaskRestConf(object):
    RESTFUL_JSON = {'default': str}


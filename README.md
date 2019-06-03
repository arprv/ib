ib - A quick and dirty Flask based imageboard.
================================================================================

Initially written with cgi alone over the course of three days. Now rewritten
using flask, with some features added. The purpose behind this project was for
me to get some experience with HTML/SQL/JS/REST and other web
techn{iques,ologies}.

--------------------------------------------------------------------------------

JavaScript is used for image expansion, link/quote decoration, quoting through
selection and post highlighting.

`conf.py` is used to configure various parameters such as bump limit, active
thread limit, valid file size/format, etc.

`admin.py` can be used for purging of posts/threads and banning.

`tables` contains required table definitions.

`cred.py` must contain database credentials. See `cred.py_template`.

### API
* `/api/board/` --- List of threads. Does not include post data.
* `/api/threads/<id>` --- Thread fields + list of all thread posts containing
    all data except file bytes.
* `/api/posts/<id>` --- Post fileds except file bytes.
* `/api/files/<id>` --- File metadata. Use `/files/<id>` to get raw bytes.

Screenshots
---------------------
![Board](/screenshots/ib_board.png)
![Thread with expanded image](/screenshots/ib_thread.png)



API Endpoints
=============


Public API
----------
For public channel listing API info, see this doc:
https://docs.google.com/document/d/1XKXQe25sf9Tht6uIXvqb3T40KeY3BLkkexcV08wvR9M/edit



Self-documenting API
--------------------
When running the Kolibri Studio on your machine, you can browse the API docs
by going to the API Root URL: http://127.0.0.1:8000/api/



Sushibar-related endpoints
--------------------------

### api/internal/publish_channel
_Method: contentcuration.views.internal.api_publish_channel_
Publish a channel (makes it exportable to Kolibri)

    POST api/internal/publish_channel
    {
      "channel_id": "{uuid.hex}"
    }

Response

    {
      "channel": "channel_id",
      "success": True
    }

### api/internal/check_user_is_editor
_Method: contentcuration.views.internal.check_user_is_editor_
Returns whether or not user is authorized to edit the channel

    POST api/internal/check_user_is_editor
    Header:
    { "Authorization": "Token {token}"}
    Body:
    { "channel_id" : "{uuid.hex}"}

Response:

    {
      "success" : True
    }

(returns 403 if not authorized)



### api/internal/authenticate_user_internal
_Method: contentcuration.views.internal.authenticate_user_internal_
Attempts to log user in based on token, throws 400 error if user token is invalid

    POST  api/internal/authenticate_user_internal
    Header:
    { "Authorization": "Token {token}"}
    Body: ---

Response

    {
      "success" : True,
      "username" : "{username}"
    }


### api/internal/check_version
_Method: contentcuration.views.internal.check_version_
Determines whether status of ricecooker is up-to-date (includes soft warnings, hard warnings, and errors)

    POST  api/internal/check_version
    Header:
    {"Authorization": "Token {token}"}
    Body:
    {"version" : "{ricecooker version}"}

Response:

    {
    "success" : True,
    "status" : "{status const}",
    "message" : "{str}"
    }


### api/internal/file_diff
_Method: contentcuration.views.internal.file_diff_
Indicates which files in a list are not on the server

    POST  api/internal/file_diff
    Header:
    {"Authorization": "Token {token}"}
    Body:
    [List of filenames] (e.g. ["abc.mp4", "def.png"])

Response

    [List of files not in storage]

(e.g. ["abc.mp4"])


### api/internal/file_upload
_Method: contentcuration.views.internal.api_file_upload_
Uploads a file to the content curation storage

    POST  api/internal/file_upload
    Header:
    {"Authorization": "Token {token}"}
    Body: ---
    FILES: FileObject to upload

Response:

    {
      "success" : True
    }

(throws SuspiciousOperation error if checksum is invalid)



### api/internal/create_channel
_Method: contentcuration.views.internal.api_create_channel_endpoint_
Creates channel based on the passed in channel data and returns the root node's id for the chef tree

    POST  api/internal/create_channel
    Header:
    { "Authorization": "Token {token}"}
    Body:
    {"channel_data": channel data}

Response:

    {
    "success": True,
    "root": "{chef_tree id}",
    "channel_id": "{uuid.hex}"
    }


### api/internal/add_nodes
_Method: contentcuration.views.internal.api_add_nodes_to_tree_
Adds nodes to tree with corresponding parent

    POST api/internal/add_nodes
    Header:
    {"Authorization": "Token {token}"}
    Body:
    {
      "content_data" : [node data],
      "root_id" : "{parent id}"
    }

Response:

    {
    "success": True,
    "root_ids": "{node_id<\>id}"
    }

Example:

    {
    "success": True,
    "root_ids": "{abc: def}"
    }
where abc is the node id, and def is the cc node's primary key


### api/internal/finish_channel
_Method: contentcuration.views.internal.api_commit_channel_
Moves chef tree to either staging tree or main tree depending on user specification

    POST  api/internal/finish_channel
    Header:
    {"Authorization": "Token {token}"}

    Body:
    {
    "channel_id" : "{uuid.hex}",
    "stage" : {boolean}
    }

Response:

    {
    "success": True,
    "new_channel": "{uuid.hex}"
    }



### api/internal/activate_channel_internal
_Method: contentcuration.views.internal.activate_channel_internal_
Deploys a staged channel to the live channel

    POST api/internal/activate_channel_internal
    Header: ---
    Body:
    {"channel_id": "{uuid.hex}"}

Response:

    {
      "success": True
    }



### api/internal/get_tree_data
_Method: contentcuration.views.internal.get_tree_data_
Returns the complete tree hierarchy information (for tree specified in `tree`).
Note: this requests will time out for large channels, so better to use multiple
calls to `/api/internal/get_node_tree_data` (described below).

    POST  api/internal/get_tree_data
    Header: ---
    Body:
    {
    "channel_id": "{uuid.hex}",
    "tree": "{str}"
    }
    Tree can be "main", "chef", "staging", or "previous"

Response:

    {
      "success" : True,
      "tree" : [list of node dicts]
    }


Example of tree:

    [
      {
        'kind': 'topic',
        'title': 'Topic',
        'children': [
          {
            'kind': 'exercise',
            'title': 'Exercise'
            'count': 2
          }
        ]
      },
      {
        'kind': 'html5',
        'title': 'HTML Title',
        'file_size': 145990
      },
    ]


#### api/internal/get_node_tree_data
_Method: contentcuration.views.internal.get_node_tree_data_

Same functionality as `get_tree_data` but returns just one-level deep children,
for the node `node_id`. To obtain the entire tree, you need to make recursive calls
to this endpoint for each of the nodes in returned tree.

    POST  api/internal/get_node_tree_data
    Header: ---
    Body:
    {
      "channel_id": "{uuid.hex}",
      "tree": "{str}"
      "node_id": "{str}"
    }
    Tree can be "main", "chef", "staging", or "previous"

Response:

    {
      "success" : True,
      "tree" : [list of node dicts]
    }




### /api/internal/get_channel_status_bulk
_Method: contentcuration.views.internal.get_channel_status_bulk_
Returns status for a list of `channel_id`s

  POST  api/internal/get_channel_status_bulk
    Body:
    {"channel_ids": ["{uuid.hex}"]}

Response:

    {
      "statuses":{
          "{uuid.hex}": "staged"
      },
      "success": true
    }


Channel endpoints
--------------------------
### api/activate_channel
_Method: contentcuration.views.base.activate_channel_endpoint_
Moves the channel's staging tree to the main tree

    POST api/activate_channel
    Body: {"channel_id": "{uuid.hex}"}
  Response:

    {
      "success": true
    }


### api/get_staged_diff_endpoint
_Method: contentcuration.views.base.get_staged_diff_endpoint_
Gets dictionary of differences between a channel's main_tree and staging_tree

    POST api/get_staged_diff_endpoint
    Body: {"channel_id": "{uuid.hex}"}
  Response is a dict of differences in main and staging trees' date created, ricecooker version, file size, # of each content kind, # of questions, and # of subtitles

Public endpoints
--------------------------
### api/public/{version}/channels
_Method: contentcuration.views.public.get_public_channel_list_
Returns serialized json string of all public channels (url includes version of endpoint Kolibri needs, e.g. `v1`)

    GET api/public/{version}/channels
    Body: ---
  Response is a serialized json of channels

### api/public/{version}/channels/lookup/{identifier}
_Method: contentcuration.views.public.get_public_channel_lookup_
Returns serialized json string of all public channels and channels matching the identifier, which can be a token or a channel id (url includes version of endpoint Kolibri needs, e.g. `v1`)

    GET api/public/{version}/channels/lookup/{identifier}
    Body: ---
 Response is a serialized json of channels


### api/public/channel/{channel_id}
_Method: contentcuration.views.public.get_channel_name_by_id_
Returns the name of the channel that matches the id

    GET api/public/channel/{channel_id}
    Body: ---
Response:

    {
      "name": {str},
      "description": {str},
      "version": {int}
    }


All endpoints
-------------
See this document for the full list of Studio API endpoints:
https://docs.google.com/spreadsheets/d/181hSEwJ7yVmMh7LEwaHENqQetYSsbSDwybHTO_0zZM0/edit?usp=sharing

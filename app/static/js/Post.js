// Post page-related code.
import TextConfirm from  './utils/TextConfirm';
import Icons from './Icon';
import u from './Util';
import initializeEditor from './Editor';
import Tingle from 'tingle.js';

// Saving/unsaving posts.
u.sub('.savepost', 'click', function(e){
  var tg = e.currentTarget;
  u.post('/do/save_post/' + tg.getAttribute('data-pid'), {}, function(data){tg.innerHTML = 'saved';});
});

u.sub('.removesavedpost', 'click', function(e){
  var tg = e.currentTarget;
  u.post('/do/remove_saved_post/' + tg.getAttribute('data-pid'), {}, function(data){tg.innerHTML = 'removed';});
})

u.addEventForChild(document, 'click', '.delete-post', function(e, qelem){
  TextConfirm(qelem, function(){
    var reason = ""
    if(qelem.getAttribute('selfdel') != "true"){
      reason = prompt('Why are you deleting this?');
      if(!reason){return false;}
    }
    u.post('/do/delete_post', {post: document.getElementById('postinfo').getAttribute('pid'), reason: reason},
    function(data){
      if (data.status != "ok") {
        document.getElementById('delpostli').innerHTML = 'Error.';
      } else {
        document.getElementById('delpostli').innerHTML = 'removed';
        document.location.reload();
      }
    })
  });
});

u.addEventForChild(document, 'click', '.edit-title', function(e, qelem){
  var tg = e.currentTarget;
  TextConfirm(qelem, function(){
    var title = document.querySelector('.post-heading .title').innerHTML;
    var reason = prompt('Pick a new title', title);
    if(!reason){return false;}
    u.post('/do/edit_title', {'reason': reason, 'post': qelem.getAttribute('data-pid')},
    function(data){
      if (data.status != "ok") {
        tg.innerHTML = data.error;
      } else {document.location.reload();}
    });
  });
});

// Stick post
u.addEventForChild(document, 'click', '.stick-post', function(e, qelem){
  var pid = qelem.parentNode.parentNode.getAttribute('data-pid'), tg=e.currentTarget;
  TextConfirm(qelem, function(){
    u.post('/do/stick/'+pid, {post: document.getElementById('postinfo').getAttribute('pid')},
    function(data){
      if (data.status != "ok") {
        tg.innerHTML = 'Error.';
      } else {
        tg.innerHTML = 'Done';
        document.location.reload();
      }
    })
  });
});

// Wiki post
u.addEventForChild(document, 'click', '.wiki-post', function(e, qelem){
  var pid = qelem.parentNode.parentNode.getAttribute('data-pid'), tg=e.currentTarget;
  TextConfirm(qelem, function(){
    u.post('/do/wikipost/'+pid, {post: document.getElementById('postinfo').getAttribute('pid')},
    function(data){
      if (data.status != "ok") {
        tg.innerHTML = 'Error.';
      } else {
        tg.innerHTML = 'Done';
        document.location.reload();
      }
    })
  });
});

u.addEventForChild(document, 'click', '.announce-post', function(e, qelem){
  var pid = qelem.parentNode.parentNode.getAttribute('data-pid'), tg=e.currentTarget;
  TextConfirm(qelem, function(){
    u.post('/do/makeannouncement', {post: pid},
    function(data){
      if (data.status != "ok") {
        tg.innerHTML = 'Error.';
      } else {
        tg.innerHTML = 'Done';
        document.location.reload();
      }
    })
  });
});


u.sub('.editflair', 'click', function(e){
  document.getElementById('postflairs').style.display = 'block';
});

u.sub('.selflair', 'click', function(e){
  var pid=this.getAttribute('data-pid');
  var flair=this.getAttribute('data-flair');
  var nsub=this.getAttribute('data-sub'), tg=this;
  u.post('/do/flair/' + nsub + '/' + pid + '/' + flair, {post: document.getElementById('postinfo').getAttribute('pid')},
    function(data) {
      if (data.status != "ok") {
        tg.parentNode.innerHTML = 'Error. ' + data.error;
      } else {
        tg.parentNode.innerHTML = 'Done!';
        document.location.reload();
      }
    }
  )
});

u.sub('#remove-flair', 'click', function(e){
  var pid=this.getAttribute('data-pid');
  var nsub=this.getAttribute('data-sub'), tg=this;
  u.post('/do/remove_post_flair/' + nsub + '/' + pid, {post: document.getElementById('postinfo').getAttribute('pid')},
    function(data) {
      if (data.status != "ok") {
        tg.innerHTML = 'Error. ' + data.error;
      } else {
        tg.innerHTML = 'Done!';
        document.location.reload();
      }
    }
  )
});


u.addEventForChild(document, 'click', '.nsfw-post', function(e, qelem){
  var pid = qelem.parentNode.parentNode.getAttribute('data-pid'), tg=e.currentTarget;
  TextConfirm(qelem, function(){
    u.post('/do/nsfw', {post: document.getElementById('postinfo').getAttribute('pid')},
    function(data){
      if (data.status != "ok") {
        tg.innerHTML = 'Error.';
      } else {
        tg.innerHTML = 'Done';
        document.location.reload();
      }
    })
  });
});

u.addEventForChild(document, 'click', '.poll-close', function(e, qelem){
  var tg=e.currentTarget;
  TextConfirm(qelem, function(){
    u.post('/do/close_poll', {post: document.getElementById('postinfo').getAttribute('pid')},
    function(data){
      if (data.status != "ok") {
        tg.innerHTML = 'Error.';
      } else {
        tg.innerHTML = 'Done';
        document.location.reload();
      }
    })
  });
});


// post source
u.addEventForChild(document, 'click', '.post-source', function(e, qelem){
  var elem = document.getElementById('postcontent');
  var testedit = qelem.parentNode.parentNode.querySelector('.postedit s');
  if(testedit){
    testedit.click();
  }

  var oc = elem.innerHTML;
  var back =  document.createElement( "a" );
  back.classList.add("postsource");
  back.innerHTML = "<s>source</s>";
  back.onclick = function(){
    elem.innerHTML = oc;
    this.parentNode.innerHTML = '<a class="post-source">source</a>';
  };
  var h = elem.clientHeight-6;
  elem.innerHTML = '<textarea style="height: ' + h + 'px">' + document.getElementById('post-source').innerHTML + '</textarea>';
  qelem.replaceWith(back);
});


// edit post
u.addEventForChild(document, 'click', '.edit-post', function(e, qelem){
  var elem = document.getElementById('postcontent');
    var testsource = qelem.parentNode.parentNode.querySelector('.postsource s');
  if(testsource){
    testsource.click();
  }
  var oc = elem.innerHTML;
  var back =  document.createElement( "a" );
  back.classList.add("postedit");
  back.innerHTML = "<s>edit</s>";
  back.onclick = function(){
    elem.innerHTML = oc;
    this.parentNode.innerHTML = '<a class="edit-post">edit</a>';
  };
  var h = elem.clientHeight-6;
  if(h<100){
    h = 100;
  }
  elem.innerHTML = '<div id="editpost" class="cwrap markdown-editor"><textarea style="height: ' + h + 'px">' + document.getElementById('post-source').innerHTML + '</textarea></div><div style="display:none" class="error"></div><button class="pure-button pure-button-primary button-xsmall btn-editpost" data-pid="' + qelem.getAttribute('data-pid') +'">Save changes</button> <button class="pure-button button-xsmall btn-preview" data-pvid="editpost" >Preview</button><div class="cmpreview canclose" style="display:none;"><h4>Comment preview</h4><span class="closemsg">&times;</span><div class="cpreview-content"></div></div>';
  qelem.replaceWith(back);
  initializeEditor(document.getElementById('editpost'));
  document.querySelector('#editpost textarea').focus()
});


// comment source
u.addEventForChild(document, 'click', '.comment-source', function(e, qelem){
  var cid = qelem.getAttribute('data-cid');
  var elem = document.getElementById('content-' + cid);

  var testedit = qelem.parentNode.parentNode.querySelector('.edit-comment s');
  if(testedit){
    testedit.click();
  }
  var oc = elem.innerHTML;
  var back =  document.createElement( "s" );
  back.innerHTML = "source";
  back.onclick = function(){
    elem.innerHTML = oc;
    this.parentNode.innerHTML = 'source';
  };
  var h = elem.clientHeight + 28;
  elem.innerHTML = '<div class="cwrap"><textarea style="height: ' + h + 'px">' + document.getElementById('sauce-' + cid).innerHTML + '</textarea></div>';
  var cNode = qelem.cloneNode(false);
  cNode.appendChild(back)
  qelem.parentNode.replaceChild(cNode,qelem );
});

// edit comment
u.addEventForChild(document, 'click', '.edit-comment', function(e, qelem){
  var cid = qelem.getAttribute('data-cid');
  var elem = document.getElementById('content-' + cid);

  var testsource = qelem.parentNode.parentNode.querySelector('.comment-source s');
  if(testsource){
    testsource.click();
  }

  var oc = elem.innerHTML;
  var back =  document.createElement( "s" );
  back.innerHTML = "edit";
  back.onclick = function(){
    elem.innerHTML = oc;
    this.parentNode.innerHTML = 'edit';
  };
  var h = elem.clientHeight + 28;
  elem.innerHTML = '<div class="cwrap markdown-editor" id="ecomm-'+cid+'"><textarea style="height: ' + h + 'px">' + document.getElementById('sauce-' + cid).innerHTML + '</textarea></div><div style="display:none" class="error"></div><button class="pure-button pure-button-primary button-xsmall btn-editcomment" data-cid="'+cid+'">Save changes</button> <button class="pure-button button-xsmall btn-preview" data-pvid="ecomm-'+cid+'">Preview</button><div class="cmpreview canclose" style="display:none;"><h4>Comment preview</h4><span class="closemsg">&times;</span><div class="cpreview-content"></div></div>';

  var cNode = qelem.cloneNode(false);
  cNode.appendChild(back)
  qelem.parentNode.replaceChild(cNode,qelem );
  initializeEditor(document.getElementById('ecomm-'+cid));
  document.querySelector('#ecomm-'+cid+' textarea').focus()
});

u.addEventForChild(document, 'click', '.btn-editpost', function(e, qelem){
  var content=document.querySelector('#editpost textarea').value;
  qelem.setAttribute('disabled', true);
  u.post('/do/edit_txtpost/' + qelem.getAttribute('data-pid'), {content:content},
  function(data){
    if (data.status != "ok") {
      qelem.parentNode.querySelector('.error').style.display = 'block';
      qelem.parentNode.querySelector('.error').innerHTML = 'There was an error while editing: ' + data.error;
      qelem.removeAttribute('disabled');
    } else {
      qelem.innerHTML = 'Saved.';
      document.location.reload();
    }
  }, function(){
    qelem.parentNode.querySelector('.error').style.display = 'block';
    qelem.parentNode.querySelector('.error').innerHTML = 'Could not contact the server';
    qelem.removeAttribute('disabled');
  })
});

u.addEventForChild(document, 'click', '.btn-editcomment', function(e, qelem){
  var cid = qelem.getAttribute('data-cid');
  var content = document.querySelector('#ecomm-' + cid + ' textarea').value;
  qelem.setAttribute('disabled', true);
  u.post('/do/edit_comment', {cid: cid, text: content},
  function(data){
    if (data.status != "ok") {
      qelem.parentNode.querySelector('.error').style.display = 'block';
      qelem.parentNode.querySelector('.error').innerHTML = 'There was an error while editing: ' + data.error;
      qelem.removeAttribute('disabled');
    } else {
      qelem.innerHTML = 'Saved.';
      document.location.reload();
    }
  }, function(){
    qelem.parentNode.querySelector('.error').style.display = 'block';
    qelem.parentNode.querySelector('.error').innerHTML = 'Could not contact the server';
    qelem.removeAttribute('disabled');
  })
});

u.addEventForChild(document, 'click', '.btn-preview', function(e, qelem){
  e.preventDefault();
  if(qelem.getAttribute('data-txid')){
    var content = document.querySelector('#' + qelem.getAttribute('data-txid')).value;
  }else{
    var content = document.querySelector('#' + qelem.getAttribute('data-pvid') + ' textarea').value;
  }
  if(content == ''){return;}
  qelem.setAttribute('disabled', true);
  qelem.innerHTML = 'Loading...';
  u.post('/do/preview', {text: content},
  function(data){
    if (data.status == "ok") {
      qelem.parentNode.querySelector('.cpreview-content').innerHTML = data.text;
      qelem.parentNode.querySelector('.cmpreview').style.display = 'block';
    } else {
      qelem.parentNode.querySelector('.error').style.display = 'block';
      qelem.parentNode.querySelector('.error').innerHTML = 'Could not contact server ';
      qelem.removeAttribute('disabled');
    }
    qelem.removeAttribute('disabled');
    qelem.innerHTML = 'Preview';
  }, function(){
    qelem.parentNode.querySelector('.error').style.display = 'block';
    qelem.parentNode.querySelector('.error').innerHTML = 'Could not contact the server';
    qelem.removeAttribute('disabled');
  })
});

// Delete comment
u.addEventForChild(document, 'click', '.delete-comment', function(e, qelem){
  // confirmation
  var cid = qelem.getAttribute('data-cid'), tg=qelem;
  TextConfirm(qelem, function(){
    var reason = ''
    if(qelem.getAttribute('selfdel') != "true"){
      reason = prompt('Why are you deleting this?');
      if(!reason){return false;}
    }
    u.post('/do/delete_comment', {cid: cid, 'reason': reason},
    function(data){
      if (data.status != "ok") {
        tg.parentNode.innerHTML = 'Error.';
      } else {
        tg.parentNode.innerHTML = 'comment removed';
        document.location.reload();
      }
    })
  });
});

// Grab post title from url
u.sub('#graburl', 'click', function(e){
  e.preventDefault();
  var uri = document.getElementById('link').value
  if(uri === ''){return;}
  this.setAttribute('disabled', true);
  this.innerHTML = 'Grabbing...';
  u.post('/do/grabtitle', {u: uri},
  function(data){
    if(data.status == 'error'){
      document.getElementById('title').value = 'Error fetching title';
      document.getElementById('graburl').removeAttribute('disabled');
      document.getElementById('graburl').innerHTML = 'Grab title';
    }else{
      document.getElementById('title').value = data.title;
      document.getElementById('graburl').removeAttribute('disabled');
      document.getElementById('graburl').innerHTML = 'Grab again';
    }
  })
})

// Load children
u.addEventForChild(document, 'click', '.loadchildren', function(e, qelem){
  qelem.textContent = "Loading...";
  e.preventDefault();
  u.post('/do/get_children/' + qelem.getAttribute('data-pid') + '/' + qelem.getAttribute('data-cid'), {},
  function(data){
    qelem.parentNode.innerHTML = data;
    Icons.rendericons();
  },function(){
    qelem.textContent = "Error.";
  })
});

u.addEventForChild(document, 'click', '.loadsibling', function(e, qelem){
  qelem.textContent = "Loading...";
  e.preventDefault();
  var pid = qelem.getAttribute('data-pid');
  var key = qelem.getAttribute('data-key');
  var parent = qelem.getAttribute('data-pcid');
  if(parent == ''){
    parent = 'null';
  }
  if(key === ''){
    var uri = '/do/get_children/' + pid + '/' + parent;
  }else{
    var uri = '/do/get_children/' + pid + '/' + parent + '/' + key;
  }
  u.post(uri, {},
  function(data){
    qelem.outerHTML = data;
    Icons.rendericons();
  },function(){
    qelem.textContent = "Error.";
  })
});

// collapse/expand comment
u.addEventForChild(document, 'click', '.togglecomment', function(e, qelem){
  var cid = qelem.getAttribute('data-cid');
  console.log(document.querySelector('#comment-'+cid+' .votecomment'))
  qelem.innerHTML = '[+]';
  if(qelem.classList.contains('collapse')){
    var sty = 'none';
    qelem.classList.remove('collapse');
    qelem.classList.add('expand');
    qelem.parentNode.parentNode.style['margin-left'] = '1.6em';
  } else {
    var sty = 'block'
    qelem.innerHTML = '[–]';
    qelem.classList.add('collapse');
    qelem.classList.remove('expand');
    qelem.parentNode.parentNode.style['margin-left'] = '0';
  }
  document.querySelector('#comment-'+cid+' .votecomment').style.display = sty;
  document.querySelector('#comment-'+cid+' .bottombar').style.display = sty;
  document.querySelector('#comment-'+cid+' .commblock .content').style.display = sty;
  document.querySelector('#child-'+cid).style.display = sty;
})

// reply to comment
u.addEventForChild(document, 'click', '.reply-comment', function(e, qelem){
  var cid = qelem.getAttribute('data-to');
  var pid = qelem.getAttribute('data-pid');
  var back =  document.createElement( "s" );
  back.innerHTML = "reply";
  back.onclick = function(){
    console.log('ob')
    document.querySelector('#rblock-' + cid).outerHTML = ''
    this.parentNode.innerHTML = 'reply'
  };
  var pN = qelem.parentNode;
  var cNode = qelem.cloneNode(false);
  cNode.appendChild(back)
  pN.replaceChild(cNode,qelem );

  var cs = window.getSelection().anchorNode;
  var pp = "";
  if(cs){
    if(cs.parentNode.parentNode && cs.parentNode.parentNode.classList.contains('content')){
      pp = '> ' + window.getSelection().getRangeAt(0).cloneContents().textContent + '\n';
    }
  }

  var lm = document.createElement('div');
  lm.id = 'rblock-' + cid;
  lm.classList.add('replybox');
  lm.innerHTML ='<div class="cwrap markdown-editor" id="rcomm-'+cid+'"><textarea class="exalert" style="height: 8em;"></textarea></div><div style="display:none" class="error"></div><button class="pure-button pure-button-primary button-xsmall btn-postcomment" data-pid="'+pid+'" data-cid="'+cid+'">Post comment</button> <button class="pure-button button-xsmall btn-preview" data-pvid="rcomm-'+cid+'">Preview</button><div class="cmpreview canclose" style="display:none;"><h4>Comment preview</h4><span class="closemsg">&times;</span><div class="cpreview-content"></div></div>';
  pN.parentNode.parentNode.appendChild(lm);
  initializeEditor(document.querySelector('#rcomm-' + cid));
  document.querySelector('#rcomm-'+cid+' textarea').focus()
  // pre-populate textarea if there's a comment selected.
  console.log('fuck', pp)
  if(pp){
    var ta = document.querySelector('#rcomm-'+cid+' textarea');
    ta.value = pp;
    ta.setSelectionRange(ta.value.length,ta.value.length);
  }

});

u.addEventForChild(document, 'click', '.btn-postcomment', function(e, qelem){
  e.preventDefault();
  var cid = qelem.getAttribute('data-cid');
  var pid = qelem.getAttribute('data-pid');
  var content = document.querySelector('#rcomm-' + cid + ' textarea').value;
  qelem.setAttribute('disabled', true);
  window.sending = true;
  u.post('/do/sendcomment/' + pid, {parent: cid, post: pid, comment: content},
  function(data){
    if (data.status != "ok") {
      qelem.parentNode.querySelector('.error').style.display = 'block';
      qelem.parentNode.querySelector('.error').innerHTML = 'There was an error while editing: ' + data.error;
      qelem.removeAttribute('disabled');
    } else {
      qelem.innerHTML = 'Saved.';
      var cmtcount = document.getElementById('cmnts');
      window.sending = false;
      if(cmtcount.getElementsByTagName('a').length === 0){
        var a = document.createElement('a')
        a.href = '/p/' + pid;
        a.innerText = "1 comments";
        a.id = 'cmnts';
        cmtcount.innerText = '';
        cmtcount.appendChild(a);
        
      }else{
        var va = cmtcount.getElementsByTagName('a')[0];
        va.innerText = (parseInt(va.innerText.split(' ')[0]) + 1) + " comments";
        if(va.pathname != window.location.pathname && cid == '0'){
          document.location = data.addr;
        }
      }
      
      var div = document.createElement('div');
      div.innerHTML = data.comment.trim();

      if(cid == '0'){
        qelem.removeAttribute('disabled');
        document.querySelector('#rcomm-' + cid + ' textarea').value = '';
        cmtcount.parentNode.insertBefore(div.firstChild, cmtcount.nextSibling);
        //document.getElementById(data.cid).scrollIntoView();
      }else{
        document.querySelector('.reply-comment[data-to="' + cid + '"] s').click();
        document.getElementById('child-' + cid).prepend(div.firstChild)
      }
    }
  }, function(){
    qelem.parentNode.querySelector('.error').style.display = 'block';
    qelem.parentNode.querySelector('.error').innerHTML = 'Could not contact the server';
    qelem.removeAttribute('disabled');
  })
});


u.addEventForChild(document, 'click', '.report-post', function(e, qelem){
  var pid = qelem.parentNode.parentNode.parentNode.getAttribute('pid');
  var modal = new Tingle.modal({
  });

  // set content
  modal.setContent('<h2>Report post</h2>\
    <p><i>This report will be forwarded to the site administration</i></p>\
    <form class="pure-form pure-form-aligned"> \
      <div class="pure-control-group"> \
        <label for="report_reason">Select a reason to report this post:</label>\
        <select name="report_reason" id="report_reason">\
          <option value="" disabled selected>Select one..</option> \
          <option value="spam">SPAM</option> \
          <option value="tos">TOS violation</option> \
          <option value="other">Other</option> \
        </select>\
      </div> \
      <div class="pure-control-group" style="display:none" id="report_text_set"> \
        <label for="report_text">Explain why you\'re reporting this post:</label>\
        <input type="text" name="report_text" id="report_text" style="width:50%" /> \
      </div> \
      <div class="pure-controls"> \
        <div style="display:none" class="error">{{error}}</div> \
        <button type="button" class="pure-button" id="submit_report" disabled data-pid=' + pid + '>Submit</button>\ \
      </div> \
    </form>\
      ');


  // open modal
  modal.open();

})

u.addEventForChild(document, 'click', '.report-comment', function(e, qelem){
  var cid = qelem.getAttribute('cid');
  var modal = new Tingle.modal({
  });

  // set content
  modal.setContent('<h2>Report comment</h2>\
    <p><i>This report will be forwarded to the site administration</i></p>\
    <form class="pure-form pure-form-aligned"> \
      <div class="pure-control-group"> \
        <label for="report_reason">Select a reason to report this post:</label>\
        <select name="report_reason" id="report_reason">\
          <option value="" disabled selected>Select one..</option> \
          <option value="spam">SPAM</option> \
          <option value="tos">TOS violation</option> \
          <option value="other">Other</option> \
        </select>\
      </div> \
      <div class="pure-control-group" style="display:none" id="report_text_set"> \
        <label for="report_text">Explain why you\'re reporting this post:</label>\
        <input type="text" name="report_text" id="report_text" style="width:50%" /> \
      </div> \
      <div class="pure-controls"> \
        <div style="display:none" class="error">{{error}}</div> \
        <button type="button" class="pure-button" id="submit_report" disabled data-cid=' + cid + '>Submit</button>\ \
      </div> \
    </form>\
      ');


  // open modal
  modal.open();

})

u.addEventForChild(document, 'change', '#report_reason', function(e, qelem){
  if(qelem.value != '' && qelem.value != 'other'){
    document.getElementById('submit_report').removeAttribute('disabled');
    document.getElementById('report_text_set').style.display='none';
  }else if(qelem.value == 'other'){
    if(document.getElementById('report_text').value.length < 3){
      document.getElementById('submit_report').setAttribute('disabled', 'true');
    }
    document.getElementById('report_text_set').style.display='block';
  }
});

u.addEventForChild(document, 'keyup', '#report_text', function(e, qelem){
  if(qelem.value.length > 3){
    document.getElementById('submit_report').removeAttribute('disabled');
  }else{
    document.getElementById('submit_report').setAttribute('disabled', 'true');
  }
});

u.addEventForChild(document, 'click', '#submit_report', function(e, qelem){
  var pid=qelem.getAttribute('data-pid');

  var errorbox = qelem.parentNode.querySelector('.error');

  var reason = document.getElementById('report_reason').value;
  if(reason == 'other'){
    reason = document.getElementById('report_text').value;
  }

  qelem.setAttribute('disabled', true);
  var uri = '/do/report'
  if(!pid){
    pid = qelem.getAttribute('data-cid');
    uri = '/do/report/comment'
  }
  u.post(uri, {post: pid, reason: reason},
  function(data){
    if (data.status != "ok") {
      errorbox.style.display = 'block';
      errorbox.innerHTML = 'Error: ' + data.error;
      qelem.removeAttribute('disabled');
    } else {
      qelem.parentNode.parentNode.parentNode.innerHTML = 'Your report has been sent and will be reviewed by the site administrators.'
    }
  }, function(){
    errorbox.style.display = 'block';
    errorbox.innerHTML = 'Could not contact the server';
    qelem.removeAttribute('disabled');
  })
});


u.addEventForChild(document, 'click', 'a.unblk', function(e, qelem){
  var sid=qelem.parentNode.parentNode.getAttribute('data-sid');
  TextConfirm(qelem, function(){
    u.post('/do/block/' + sid, {},
    function(data){
      if (data.status == "ok") {
        document.location.reload();
      }
    });
  });
});

function send_mail(channel, email){
  return new Promise(function(resolve, reject){
    var data = {
      "channel_id": channel.get("id"),
      "user_email": email
    };
    $.ajax({
      method:"POST",
        url: window.Urls.send_invitation_email(),
        data:  JSON.stringify(data),
        success:function(data){
          var Models = require("edit_channel/models");
          resolve(new Models.InvitationModel(JSON.parse(data)));
        },
        error:function(error){
          reject(error);
        }
    });
  });
}

module.exports = {
  send_mail : send_mail
}
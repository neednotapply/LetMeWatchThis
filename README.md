# Installation Instructions
Create a new application at https://discord.com/developers/applications  

### General Information
Add a Name and App Icon.  
If you intend to make the bot public, upload the ToS and Privacy Policy to `https://gist.github.com/` or `https://pastebin.com/` and update the URLs appropriately.

### Installation
Take note of your installation link, this is how you can add your bot to a server.  
The bot requires the following SCOPES: `applications.commands` `bot`  
The bot requires the following Permissions: `Embed Links` `Send Messages`

### Oauth2
This section can be ignored.

### Bot
Add the Banner and make any necessary adjustments to the Name / Icon.  
Take note of your `Token`, you will need it later. Do not share this with anyone.  
Ensure that `Message Content Intent` is enabled.  
If you intend to make the bot public, ensure that `Public Bot` is enabled.

## OMDB API
This bot uses the OMDB API to fetch information on media.  
You need an API key which you can acquire for free here `https://www.omdbapi.com/apikey.aspx`

## Config.json
Either clone the repository or download as a zip.  
Open `config.json` and enter your Bot Token, Guild ID, OMDB API Key, and Owner ID (Discord name)

## Bot.js
Download and Install Node.js  
Ensure you have the prerequisite packages installed from NPM: `npm install discord.js axios cheerio`  
Navigate to your installation directory and open a terminal, run the bot with `node bot.js`  

Enjoy 👍

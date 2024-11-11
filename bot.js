const { Client, GatewayIntentBits, SlashCommandBuilder, EmbedBuilder } = require('discord.js');
const axios = require('axios');
const cheerio = require('cheerio');
const { token, omdbApiKey } = require('./config.json');

const client = new Client({
    intents: [
        GatewayIntentBits.Guilds,
        GatewayIntentBits.MessageContent
    ]
});

// Function to truncate a string to a maximum length
function truncateString(str, maxLen) {
    return str.length > maxLen ? str.slice(0, maxLen - 3) + '...' : str;
}

client.once('ready', async () => {
    console.log('Bot is ready!');

    // Register slash commands
    const commands = [
        new SlashCommandBuilder()
            .setName('ping')
            .setDescription('Replies with Pong!'),
        new SlashCommandBuilder()
            .setName('watch')
            .setDescription('Searches for a movie or TV show using OMDB, Primewire, and Fmovies')
            .addStringOption(option =>
                option.setName('title')
                    .setDescription('Title of the movie or TV show')
                    .setRequired(true))
    ];

    const commandData = commands.map(command => command.toJSON());
    try {
        await client.application.commands.set(commandData);
        console.log('Slash commands registered successfully!');
    } catch (error) {
        console.error('Error registering slash commands:', error);
    }
});

client.on('interactionCreate', async interaction => {
    if (!interaction.isCommand()) return;

    const { commandName, options } = interaction;

    if (commandName === 'ping') {
        await interaction.reply('Pong!');
    } else if (commandName === 'watch') {
        const mediaTitle = options.getString('title');
        if (!mediaTitle) {
            await interaction.reply('Please provide a movie or TV show title.');
            return;
        }

        try {
            // Retrieve media data from OMDB API
            const omdbResponse = await axios.get(`http://www.omdbapi.com/?apikey=${omdbApiKey}&t=${encodeURIComponent(mediaTitle)}`);
            const mediaData = omdbResponse.data;

            if (mediaData.Response === 'False') {
                await interaction.reply('Media not found.');
                return;
            }

            // Perform a search on Primewire.tf
            const primewireUrl = `https://primewire.tf/search/${encodeURIComponent(mediaTitle.replace(/\s+/g, '-'))}`;
            const primewireResponse = await axios.get(primewireUrl);
            const $primewire = cheerio.load(primewireResponse.data);

            // Retrieve the top 20 search results from Primewire.mx
            const primewireLinks = [];
            for (let i = 2; i < 22; i++) {
                const mediaLinkElement = $primewire(`div.fbr-content.fbr-line:nth-of-type(${i}) a`);
                const mediaLink = `https://primewire.tf${mediaLinkElement.attr('href')}`;
                const mediaTitle = mediaLinkElement.text().trim();
                if (mediaLink && mediaTitle) {
                    primewireLinks.push({ title: truncateString(mediaTitle, 100), link: mediaLink });
                }
            }

            // Perform a search on Fmovies
            const fmoviesUrl = `https://en.fmoviesz-to.com/filter?keyword=${encodeURIComponent(mediaTitle.replace(/\s+/g, '+').replace(/([()])/g, encodeURIComponent))}`;
            const fmoviesResponse = await axios.get(fmoviesUrl);
            const $fmovies = cheerio.load(fmoviesResponse.data);

            // Retrieve the top 20 search results from Fmovies
            const fmoviesLinks = [];
            for (let i = 1; i < 21; i++) {
                const mediaLinkElement = $fmovies(`div.item:nth-of-type(${i}) .meta a`);
                const mediaLink = `https://en.fmoviesz-to.com${mediaLinkElement.attr('href')}`;
                const mediaTitle = mediaLinkElement.text().trim();
                if (mediaLink && mediaTitle) {
                    fmoviesLinks.push({ title: truncateString(mediaTitle, 100), link: mediaLink });
                }
            }

            // Filter the links based on the search query and OMDB title
            const filteredPrimewireLinks = primewireLinks.filter(link => link.title.toLowerCase().includes(mediaTitle.toLowerCase()) || mediaData.Title.toLowerCase().includes(link.title.toLowerCase())).slice(0, 5);
            const filteredFmoviesLinks = fmoviesLinks.filter(link => link.title.toLowerCase().includes(mediaTitle.toLowerCase()) || mediaData.Title.toLowerCase().includes(link.title.toLowerCase())).slice(0, 5);

            // Construct the embed with data from both sources
            const embed = new EmbedBuilder()
                .setTitle(mediaData.Title)
                .setColor(0x0099FF)
                .setDescription(`Release Year: ${mediaData.Year}\nIMDB Rating: ${mediaData.imdbRating}\nRotten Tomatoes Rating: ${mediaData.Ratings.find(rating => rating.Source === 'Rotten Tomatoes')?.Value || 'N/A'}\n\n${mediaData.Plot}`)
                .setThumbnail(mediaData.Poster);

            // Add fields for filtered Primewire and Fmovies links
            if (filteredPrimewireLinks.length > 0) {
                embed.addFields({ name: 'Top Primewire Results:', value: filteredPrimewireLinks.map(({ title, link }) => `[${title}](${link})`).join('\n') });
            } else {
                embed.addFields({ name: 'Top Primewire Results:', value: 'No results found.' });
            }

            if (filteredFmoviesLinks.length > 0) {
                embed.addFields({ name: 'Top Fmovies Results:', value: filteredFmoviesLinks.map(({ title, link }) => `[${title}](${link})`).join('\n') });
            } else {
                embed.addFields({ name: 'Top Fmovies Results:', value: 'No results found.' });
            }

            await interaction.reply({ embeds: [embed] });
        } catch (error) {
            console.error('Error fetching media data:', error);
            await interaction.reply('An error occurred while fetching media data.');
        }
    }
});

client.login(token);

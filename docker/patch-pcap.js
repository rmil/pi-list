// Patches dist/api/pcap.js: replace deprecated -map_channel with -filter_complex pan
const fs = require('fs');
let src = fs.readFileSync('/app/listwebserver/dist/api/pcap.js', 'utf8');

const oldCode = `const channelMapping = channels
            .split(',')
            .slice(0, 16)
            .map(function (i) {
            return '-map_channel 0.0.' + i;
        })
            .join(' ');`;

const newCode = `// Note: -map_channel was removed in ffmpeg 5.x, use -filter_complex pan instead
        const selectedChannels = channels.split(',').slice(0, 16);
        const outChannelCount = selectedChannels.length;
        const channelLayout = outChannelCount === 1 ? 'mono' : \`\${outChannelCount}c\`;
        const panMapping = selectedChannels.map((i, idx) => \`c\${idx}=c\${i}\`).join('|');
        const channelMapping = \`-filter_complex "[0:a]pan=\${channelLayout}|\${panMapping}[out]" -map "[out]"\`;`;

if (!src.includes(oldCode)) {
    console.error('ERROR: patch target not found in pcap.js');
    process.exit(1);
}

src = src.replace(oldCode, newCode);
fs.writeFileSync('/app/listwebserver/dist/api/pcap.js', src);
console.log('Patched pcap.js OK');

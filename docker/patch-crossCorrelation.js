// Patches dist/analyzers/crossCorrelation.js: replace deprecated -map_channel with -filter_complex pan
const fs = require('fs');
let src = fs.readFileSync('/app/listwebserver/dist/analyzers/crossCorrelation.js', 'utf8');

const oldCode = `const ffmpegCommand = \`ffmpeg -hide_banner -y -f s\${encodingBits}be -ar \${sampling}k -ac \${channelNumber} -i "\${inputFile}" -map_channel 0.0.\${parseInt(channel) - 1} -f \${outputFormat} -acodec pcm_\${outputFormat} "\${outputFile}"\`;`;

const newCode = `// Note: -map_channel was removed in ffmpeg 5.x, use -filter_complex pan instead
    const chIdx = parseInt(channel) - 1;
    const ffmpegCommand = \`ffmpeg -hide_banner -y -f s\${encodingBits}be -ar \${sampling}k -ac \${channelNumber} -i "\${inputFile}" -filter_complex "[0:a]pan=mono|c0=c\${chIdx}[out]" -map "[out]" -f \${outputFormat} -acodec pcm_\${outputFormat} "\${outputFile}"\`;`;

if (!src.includes(oldCode)) {
    console.error('ERROR: patch target not found in crossCorrelation.js');
    process.exit(1);
}

src = src.replace(oldCode, newCode);
fs.writeFileSync('/app/listwebserver/dist/analyzers/crossCorrelation.js', src);
console.log('Patched crossCorrelation.js OK');

#!/bin/bash
USER_AGENT="Mozilla/5.0 (Windows; U; Windows NT 6.1; en-US) AppleWebKit/533.20.25 (KHTML, like Gecko) Version/5.0.4 Safari/533.20.27"

mkdir -p data

"./wget-lua" \
    "-U" "$USER_AGENT" \
    "--lua-script" "xanga.lua" \
    "--no-check-certificate" \
    "--output-document" "data/tmp-$1" \
    "--truncate-output" \
    "-e" "robots=off" \
    "-nv" "-o" "wget-$1.log" \
    "--recursive" "--level=inf" \
    "--exclude-domains=vi.xanga.com" \
    "--rotate-dns" \
    "--page-requisites" \
    "--timeout" "10" \
    "--tries" "20" \
    "--waitretry" "5" \
    "--warc-file" "data/$1.warc.gz" \
    "--warc-header" "operator: Archive Team" \
    "$2"


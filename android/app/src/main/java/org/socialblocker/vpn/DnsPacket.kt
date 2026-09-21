package org.socialblocker.vpn

/**
 * Just enough IPv4/UDP/DNS to run a sinkhole.
 *
 * WHY THIS EXISTS AT ALL. On Linux the enforcement engine writes a fenced
 * region into /etc/hosts and the resolver does the rest. Android has no
 * writable hosts file without root, so the equivalent hook is `VpnService`:
 * the app advertises itself as the DNS server, the OS hands it the raw packets
 * apps send there, and this file turns those bytes into a question we can
 * answer or forward.
 *
 * Deliberately narrow, because every line here runs on the path of every
 * connection the phone makes:
 *   - IPv4 only. The tunnel advertises exactly one IPv4 resolver, so nothing in
 *     the VPN has an IPv6 resolver to talk to. That closes the bypass by
 *     configuration instead of by parsing a second address family.
 *   - UDP only. A DNS query that falls back to TCP is forwarded untouched by
 *     the route configuration (it never enters the tunnel).
 *   - Fragments are dropped rather than reassembled. A fragmented DNS query is
 *     not a thing that happens on a working network.
 */
internal object DnsPacket {

    const val PROTO_UDP = 17
    const val DNS_PORT = 53

    /** A parsed DNS query still sitting in its packet buffer. */
    data class Query(
        val srcIp: ByteArray,
        val dstIp: ByteArray,
        val srcPort: Int,
        val dstPort: Int,
        val ipId: Int,
        /** Offset of the DNS message inside the original packet buffer. */
        val dnsOffset: Int,
        val dnsLength: Int,
        val name: String,
        val qtype: Int,
        /** Offset just past the question section, relative to [dnsOffset]. */
        val questionEnd: Int,
    )

    fun u16(b: ByteArray, i: Int): Int =
        ((b[i].toInt() and 0xFF) shl 8) or (b[i + 1].toInt() and 0xFF)

    fun putU16(b: ByteArray, i: Int, v: Int) {
        b[i] = ((v ushr 8) and 0xFF).toByte()
        b[i + 1] = (v and 0xFF).toByte()
    }

    /**
     * Parse an IPv4/UDP/DNS query out of [packet], or return null if it is not
     * one we should answer. Null means "not ours" and the caller drops it; the
     * tunnel only routes our own resolver address, so that is a rare case and
     * dropping is safe.
     */
    fun parseQuery(packet: ByteArray, length: Int): Query? {
        if (length < 28) return null
        if ((packet[0].toInt() and 0xF0) != 0x40) return null          // IPv4 only
        val ihl = (packet[0].toInt() and 0x0F) * 4
        if (ihl < 20 || length < ihl + 8) return null
        if ((packet[9].toInt() and 0xFF) != PROTO_UDP) return null
        // Fragment offset non-zero, or More-Fragments set -> not a whole query.
        if ((u16(packet, 6) and 0x3FFF) != 0) return null

        val dstPort = u16(packet, ihl + 2)
        if (dstPort != DNS_PORT) return null

        val udpLen = u16(packet, ihl + 4)
        if (udpLen < 8) return null
        val dnsOffset = ihl + 8
        val dnsLength = minOf(udpLen - 8, length - dnsOffset)
        if (dnsLength < 12) return null

        val parsed = readQuestion(packet, dnsOffset, dnsLength) ?: return null

        return Query(
            srcIp = packet.copyOfRange(12, 16),
            dstIp = packet.copyOfRange(16, 20),
            srcPort = u16(packet, ihl),
            dstPort = dstPort,
            ipId = u16(packet, 4),
            dnsOffset = dnsOffset,
            dnsLength = dnsLength,
            name = parsed.first,
            qtype = parsed.second,
            questionEnd = parsed.third,
        )
    }

    /**
     * Read the first question: (name, qtype, offset-past-question).
     *
     * Questions never use name compression, so this is a plain label walk. The
     * bounds checks are not ceremony — this parses bytes that any app on the
     * phone can hand us, and an unchecked length byte here is a crash in the
     * service that enforces the block.
     */
    private fun readQuestion(b: ByteArray, off: Int, len: Int): Triple<String, Int, Int>? {
        if (u16(b, off + 4) < 1) return null          // QDCOUNT
        val sb = StringBuilder()
        var i = 12
        while (true) {
            if (i >= len) return null
            val labelLen = b[off + i].toInt() and 0xFF
            if (labelLen == 0) { i += 1; break }
            if (labelLen > 63) return null            // compression pointer or junk
            if (i + 1 + labelLen > len) return null
            if (sb.isNotEmpty()) sb.append('.')
            sb.append(String(b, off + i + 1, labelLen, Charsets.US_ASCII))
            i += 1 + labelLen
        }
        if (i + 4 > len) return null
        val qtype = u16(b, off + i)
        return Triple(sb.toString(), qtype, i + 4)
    }

    /**
     * Build the sinkhole answer for a blocked name.
     *
     * An A query is answered with 0.0.0.0, which fails the connection
     * immediately. The desktop sinks to 127.0.0.1, but on a phone that address
     * can reach a real local server in another app, so 0.0.0.0 is the honest
     * translation of the same intent.
     *
     * Anything else (AAAA, HTTPS/SVCB, TXT) gets NOERROR with zero answers
     * rather than NXDOMAIN. That is the difference between an app showing
     * "no connection" and an app retrying the lookup in a tight loop on the
     * user's battery.
     */
    fun blockedResponse(q: Query, packet: ByteArray): ByteArray {
        val questionBytes = q.questionEnd - 12
        val isA = q.qtype == 1
        val answerLen = if (isA) 16 else 0
        val out = ByteArray(12 + questionBytes + answerLen)

        // Header: same id, QR=1, opcode+RD copied from the query, RA=1, RCODE=0.
        out[0] = packet[q.dnsOffset]
        out[1] = packet[q.dnsOffset + 1]
        val reqFlags = packet[q.dnsOffset + 2].toInt() and 0xFF
        out[2] = (0x80 or (reqFlags and 0x78) or (reqFlags and 0x01)).toByte()
        out[3] = 0x80.toByte()                       // RA set, NOERROR
        putU16(out, 4, 1)                            // QDCOUNT
        putU16(out, 6, if (isA) 1 else 0)            // ANCOUNT
        putU16(out, 8, 0)                            // NSCOUNT
        putU16(out, 10, 0)                           // ARCOUNT

        System.arraycopy(packet, q.dnsOffset + 12, out, 12, questionBytes)

        if (isA) {
            var i = 12 + questionBytes
            out[i] = 0xC0.toByte(); out[i + 1] = 0x0C   // pointer back to the question name
            putU16(out, i + 2, 1)                       // TYPE A
            putU16(out, i + 4, 1)                       // CLASS IN
            putU16(out, i + 6, 0); putU16(out, i + 8, 60)   // TTL 60s
            putU16(out, i + 10, 4)                      // RDLENGTH
            // RDATA 0.0.0.0 — the array is already zeroed.
        }
        return out
    }

    /**
     * Wrap [payload] in a UDP/IPv4 packet ready to be written back to the tun
     * device, with both checksums computed.
     *
     * The UDP checksum is mandatory here even though it is optional in IPv4:
     * Android's own netd drops a tunnelled reply with a wrong one, and the
     * failure looks exactly like "DNS is broken" rather than like a bug.
     */
    fun buildUdpPacket(
        srcIp: ByteArray, dstIp: ByteArray, srcPort: Int, dstPort: Int,
        payload: ByteArray, payloadLen: Int, ipId: Int,
    ): ByteArray {
        val total = 20 + 8 + payloadLen
        val p = ByteArray(total)

        p[0] = 0x45                                  // IPv4, 20-byte header
        putU16(p, 2, total)
        putU16(p, 4, ipId)
        putU16(p, 6, 0x4000)                         // Don't Fragment
        p[8] = 64                                    // TTL
        p[9] = PROTO_UDP.toByte()
        System.arraycopy(srcIp, 0, p, 12, 4)
        System.arraycopy(dstIp, 0, p, 16, 4)
        putU16(p, 10, fold(sum16(p, 0, 20)))         // header checksum

        putU16(p, 20, srcPort)
        putU16(p, 22, dstPort)
        putU16(p, 24, 8 + payloadLen)
        System.arraycopy(payload, 0, p, 28, payloadLen)

        // Pseudo-header (src, dst, zero, proto, udp length) + header + payload.
        var s = sum16(p, 12, 8)
        s += PROTO_UDP.toLong()
        s += (8 + payloadLen).toLong()
        s += sum16(p, 20, 8 + payloadLen)
        var c = fold(s)
        if (c == 0) c = 0xFFFF                       // 0 means "no checksum" on the wire
        putU16(p, 26, c)
        return p
    }

    private fun sum16(b: ByteArray, offset: Int, length: Int): Long {
        var sum = 0L
        var i = offset
        var left = length
        while (left > 1) {
            sum += (((b[i].toInt() and 0xFF) shl 8) or (b[i + 1].toInt() and 0xFF)).toLong()
            i += 2; left -= 2
        }
        if (left > 0) sum += ((b[i].toInt() and 0xFF) shl 8).toLong()
        return sum
    }

    private fun fold(sumIn: Long): Int {
        var sum = sumIn
        while ((sum ushr 16) != 0L) sum = (sum and 0xFFFF) + (sum ushr 16)
        return (sum.inv() and 0xFFFF).toInt()
    }
}

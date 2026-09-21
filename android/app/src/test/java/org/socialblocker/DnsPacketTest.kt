package org.socialblocker

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.socialblocker.vpn.DnsPacket

/**
 * The packet layer is the riskiest code in the app and the only part with no
 * safe failure mode: a wrong checksum does not look like a bug, it looks like
 * "the internet is broken on this phone". It is also pure byte arithmetic with
 * no Android in it, so it can be tested properly here rather than guessed at on
 * a device.
 *
 * The checksums are verified against an independent implementation written in
 * this file. Re-using the production helper would only prove it agrees with
 * itself.
 */
class DnsPacketTest {

    @Test
    fun `a well-formed query is parsed`() {
        val packet = query("instagram.com", qtype = 1)
        val q = DnsPacket.parseQuery(packet, packet.size)
        assertNotNull(q)
        assertEquals("instagram.com", q!!.name)
        assertEquals(1, q.qtype)
        assertEquals(53, q.dstPort)
        assertEquals(40000, q.srcPort)
    }

    @Test
    fun `packets that are not ours are rejected rather than parsed`() {
        val good = query("example.com", 1)

        val v6 = good.copyOf().also { it[0] = 0x60.toByte() }
        assertNull(DnsPacket.parseQuery(v6, v6.size))

        val tcp = good.copyOf().also { it[9] = 6 }
        assertNull(DnsPacket.parseQuery(tcp, tcp.size))

        val notDns = good.copyOf().also { DnsPacket.putU16(it, 22, 443) }
        assertNull(DnsPacket.parseQuery(notDns, notDns.size))

        // A fragment: offset non-zero in the flags/fragment field.
        val frag = good.copyOf().also { DnsPacket.putU16(it, 6, 0x0001) }
        assertNull(DnsPacket.parseQuery(frag, frag.size))

        assertNull(DnsPacket.parseQuery(good, 10))              // truncated
    }

    @Test
    fun `a malformed label length is refused, not trusted`() {
        // Any app on the phone can send these bytes; an unchecked length here
        // would be a crash in the service that enforces the block.
        val packet = query("example.com", 1)
        packet[28 + 12] = 99                                     // label longer than 63
        assertNull(DnsPacket.parseQuery(packet, packet.size))
    }

    @Test
    fun `an A query for a blocked name is answered with 0_0_0_0`() {
        val packet = query("instagram.com", qtype = 1)
        val q = DnsPacket.parseQuery(packet, packet.size)!!
        val dns = DnsPacket.blockedResponse(q, packet)

        assertEquals(0x1234, DnsPacket.u16(dns, 0))              // same transaction id
        assertTrue((dns[2].toInt() and 0x80) != 0)               // QR: this is a response
        assertTrue((dns[2].toInt() and 0x01) != 0)               // RD copied from the query
        assertTrue((dns[3].toInt() and 0x80) != 0)               // RA set
        assertEquals(0, dns[3].toInt() and 0x0F)                 // RCODE 0, not NXDOMAIN
        assertEquals(1, DnsPacket.u16(dns, 4))                   // QDCOUNT
        assertEquals(1, DnsPacket.u16(dns, 6))                   // ANCOUNT

        val answer = dns.size - 16
        assertEquals(0xC00C, DnsPacket.u16(dns, answer))         // name compression pointer
        assertEquals(1, DnsPacket.u16(dns, answer + 2))          // TYPE A
        assertEquals(1, DnsPacket.u16(dns, answer + 4))          // CLASS IN
        assertEquals(4, DnsPacket.u16(dns, answer + 10))         // RDLENGTH
        for (i in 0 until 4) assertEquals(0, dns[answer + 12 + i].toInt())
    }

    @Test
    fun `a non-A query is answered empty rather than NXDOMAIN`() {
        // NXDOMAIN makes some apps retry in a tight loop; an empty NOERROR
        // makes them give up quietly.
        val packet = query("instagram.com", qtype = 28)          // AAAA
        val q = DnsPacket.parseQuery(packet, packet.size)!!
        val dns = DnsPacket.blockedResponse(q, packet)
        assertEquals(0, DnsPacket.u16(dns, 6))                   // ANCOUNT
        assertEquals(0, dns[3].toInt() and 0x0F)                 // NOERROR
    }

    @Test
    fun `the reply packet is addressed back to the asker with valid checksums`() {
        val packet = query("instagram.com", qtype = 1)
        val q = DnsPacket.parseQuery(packet, packet.size)!!
        val dns = DnsPacket.blockedResponse(q, packet)
        val reply = DnsPacket.buildUdpPacket(
            q.dstIp, q.srcIp, q.dstPort, q.srcPort, dns, dns.size, q.ipId)

        assertEquals(20 + 8 + dns.size, reply.size)
        assertEquals(reply.size, DnsPacket.u16(reply, 2))        // total length
        // Source and destination swapped: it must come from the resolver the
        // client asked, or the client discards it.
        assertEquals(q.dstIp.toList(), reply.copyOfRange(12, 16).toList())
        assertEquals(q.srcIp.toList(), reply.copyOfRange(16, 20).toList())
        assertEquals(53, DnsPacket.u16(reply, 20))
        assertEquals(40000, DnsPacket.u16(reply, 22))

        // A correct checksum makes the whole region sum to zero.
        assertEquals(0, ones(reply, 0, 20))
        assertEquals(0, udpCheck(reply))
    }

    // --- independent reference implementations ------------------------------

    /** One's-complement sum, folded and complemented. Zero means "verified". */
    private fun ones(b: ByteArray, off: Int, len: Int, seed: Long = 0): Int {
        var sum = seed
        var i = off
        var left = len
        while (left > 1) {
            sum += (((b[i].toInt() and 0xFF) shl 8) or (b[i + 1].toInt() and 0xFF)).toLong()
            i += 2; left -= 2
        }
        if (left > 0) sum += ((b[i].toInt() and 0xFF) shl 8).toLong()
        while ((sum ushr 16) != 0L) sum = (sum and 0xFFFF) + (sum ushr 16)
        return (sum.inv() and 0xFFFF).toInt()
    }

    private fun udpCheck(p: ByteArray): Int {
        val udpLen = p.size - 20
        var seed = 0L
        for (i in 12 until 20 step 2) {
            seed += (((p[i].toInt() and 0xFF) shl 8) or (p[i + 1].toInt() and 0xFF)).toLong()
        }
        seed += 17L + udpLen.toLong()
        return ones(p, 20, udpLen, seed)
    }

    /** Build an IPv4/UDP/DNS query for [name], as an app would send it. */
    private fun query(name: String, qtype: Int): ByteArray {
        val labels = name.split(".")
        val dnsLen = 12 + labels.sumOf { it.length + 1 } + 1 + 4
        val p = ByteArray(20 + 8 + dnsLen)

        p[0] = 0x45
        DnsPacket.putU16(p, 2, p.size)
        DnsPacket.putU16(p, 4, 0xABCD)
        p[8] = 64; p[9] = 17
        byteArrayOf(10, 111, 222, 1).copyInto(p, 12)     // client (the tun address)
        byteArrayOf(10, 111, 222, 2).copyInto(p, 16)     // our fake resolver

        DnsPacket.putU16(p, 20, 40000)
        DnsPacket.putU16(p, 22, 53)
        DnsPacket.putU16(p, 24, 8 + dnsLen)

        val d = 28
        DnsPacket.putU16(p, d, 0x1234)                   // transaction id
        DnsPacket.putU16(p, d + 2, 0x0100)               // standard query, RD set
        DnsPacket.putU16(p, d + 4, 1)                    // QDCOUNT
        var i = d + 12
        labels.forEach { label ->
            p[i] = label.length.toByte()
            label.toByteArray(Charsets.US_ASCII).copyInto(p, i + 1)
            i += 1 + label.length
        }
        p[i] = 0; i += 1
        DnsPacket.putU16(p, i, qtype)
        DnsPacket.putU16(p, i + 2, 1)                    // CLASS IN
        return p
    }
}

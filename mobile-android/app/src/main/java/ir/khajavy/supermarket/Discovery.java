package ir.khajavy.supermarket;

import java.net.DatagramPacket;
import java.net.DatagramSocket;
import java.net.InetAddress;

/**
 * v2.1 — finds the shop PC on the current Wi-Fi without knowing its IP.
 * Broadcasts "SMKT-FIND <link_key>" on UDP 48765; the PC that owns that key
 * answers "SMKT-HERE <port> <key> <store>" and we return its http URL.
 */
public final class Discovery {
    private Discovery() {}
    public static final int PORT = 48765;

    public static String find(String linkKey, int timeoutMs) {
        if (linkKey == null) linkKey = "";
        DatagramSocket s = null;
        try {
            s = new DatagramSocket(); s.setBroadcast(true); s.setSoTimeout(timeoutMs);
            byte[] q = ("SMKT-FIND " + linkKey).getBytes("UTF-8");
            for (String b : new String[]{"255.255.255.255"}) s.send(new DatagramPacket(q, q.length, InetAddress.getByName(b), PORT));
            // also try the subnet-directed broadcast of every interface
            try {
                java.util.Enumeration<java.net.NetworkInterface> ifs = java.net.NetworkInterface.getNetworkInterfaces();
                while (ifs != null && ifs.hasMoreElements()) { java.net.NetworkInterface ni = ifs.nextElement(); if (ni.isLoopback() || !ni.isUp()) continue; for (java.net.InterfaceAddress ia : ni.getInterfaceAddresses()) { InetAddress bc = ia.getBroadcast(); if (bc != null) s.send(new DatagramPacket(q, q.length, bc, PORT)); } }
            } catch (Exception ignore) {}
            long end = System.currentTimeMillis() + timeoutMs;
            byte[] buf = new byte[512];
            while (System.currentTimeMillis() < end) {
                DatagramPacket p = new DatagramPacket(buf, buf.length);
                s.receive(p);
                String t = new String(p.getData(), 0, p.getLength(), "UTF-8").trim();
                if (!t.startsWith("SMKT-HERE")) continue;
                String[] parts = t.split(" ", 4);
                if (parts.length < 3) continue;
                if (!linkKey.isEmpty() && !linkKey.equalsIgnoreCase(parts[2])) continue;
                if (parts.length > 3 && !parts[3].isEmpty()) Prefs.set("store_name", parts[3]);
                return "http://" + p.getAddress().getHostAddress() + ":" + parts[1];
            }
        } catch (Exception ignore) {
        } finally { if (s != null) s.close(); }
        return null;
    }
}

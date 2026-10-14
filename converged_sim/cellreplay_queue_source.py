"""Fetch pinned primary queue sources identified by upstream Makefile.am."""
import argparse
from . import cellreplay_code_source as source

FILES = ('src/packet/queued_packet.hh', 'src/packet/abstract_packet_queue.hh',
         'src/packet/dropping_packet_queue.hh', 'src/packet/dropping_packet_queue.cc',
         'src/packet/drop_tail_packet_queue.hh')

if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--out', required=True)
    a = p.parse_args()
    source.FILES = FILES
    source.fetch(a.out)

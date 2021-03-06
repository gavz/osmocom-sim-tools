#!/usr/bin/env python
# -*- coding: utf-8 -*-

#
#  Copyright (C) 2018 cheeriotb <cheerio.the.bear@gmail.com>
#
#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License version 2 as
#  published by the Free Software Foundation.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software
#  Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
#  MA 02110-1301, USA.
#/

from pySim.transport.pcsc import PcscSimLink

import argparse
import sys

class CommandInterface(object):
    def __init__(self, transport):
        self.transport = transport

    def extract_value(self, response):
        tag_first = int(response[0:2], 16)
        response = response[2:]

        # If all the bits 1-5 in the first byte are 1, the tag is encoded in the long format.
        # The tag number is encoded in the following octets,
        # where bit 8 of each is 1 if there are more octets, and bits 1–7 encode the tag number.
        if (tag_first & 0x1F) == 0x1F:
            while True:
                tag_subsequent = int(response[0:2], 16)
                response = response[2:]
                if (tag_subsequent & 0x80) != 0x80:
                    break

        length = 0
        length_byte = int(response[0:2], 16)
        response = response[2:]

        # The long form consist of 1 initial octet followed by 1 or more subsequent octets,
        # containing the length. In the initial octet, bit 8 is 1,
        # and bits 1–7 (excluding the values 0 and 127) encode the number of octets that follow.
        if length_byte > 127:
            length_size = length_byte - 128
            while length_size:
                length_byte = int(response[0:2], 16)
                response = response[2:]
                length = (length << 8) + length_byte
                length_size -= 1
        else:
            length = length_byte

        return (response[:length * 2], response[length * 2:])

    def send_apdu_raw(self, apdu):
        if len(apdu) < (4 * 2):
            raise ValueError("Specified C-APDU is too short : " + apdu)
        (response, sw) = self.transport.send_apdu(apdu)
        sw1 = int(sw[0:2], 16)
        if sw1 == 0x6C:
            if len(apdu) > 8:
                apdu = apdu[:-2] + sw[2:4]
            else:
                apdu = apdu[:8] + sw[2:4]
            (response, sw) = self.transport.send_apdu(apdu)
            sw1 = int(sw[0:2], 16)
        output = response
        while sw1 == 0x61 or sw1 == 0x9F:
            apdu = apdu[0:2] + 'C00000' + sw[2:4]
            (response, sw) = self.transport.send_apdu(apdu)
            output = output + response
            sw1 = int(sw[0:2], 16)
        return (output, sw)

    def send_terminal_profile(self):
        (response, sw) = self.transport.send_apdu('A010000011FFFF000000000000000000000000000000')
        if sw[0:2] == '91':
            self.transport.send_apdu('A0120000' + sw[2:4])
            return self.transport.send_apdu('A01400000C810301030002028281030100')
        return (response, sw)

    def open_logical_channel(self):
        (response, sw) = self.transport.send_apdu('0070000001')
        if sw[0:2] != '90':
            raise RuntimeError('Unexpected SW for MANAGE CHANNEL : ' + sw)
        if len(response) != 2:
            raise RuntimeError('The size of the response data is wrong : ' + response)
        return int(response[0:2], 16)

    def close_logical_channel(self, channel_number):
        (response, sw) = self.transport.send_apdu('007080' + format(channel_number, '02X'))
        if sw[0:2] != '90':
            raise RuntimeError('Unexpected SW for MANAGE CHANNEL : ' + sw)

    def select_application(self, channel_number, aid):
        (response, sw) = self.send_apdu_raw(format(channel_number, '02X') + 'A40400' \
                + format(len(aid) // 2, '02X') + aid + '00')
        if sw[0:2] != '90':
            raise RuntimeError('Unexpected SW for SELECT : ' + sw)
        return response

    def select_application_with_check_response(self, channel_number, aid):
        response = self.select_application(channel_number, aid)

        # The length of the select response shall be greater than 2 bytes
        if len(response) < 3:
            raise RuntimeError('The size of the response data is wrong : ' + response)

        (target, remain) = self.extract_value(response)
        while len(target) > 0:
            (value, target) = self.extract_value(target)

    def send_apdu_on_channel(self, channel_number, apdu):
        cla = int(apdu[0:2], 16)
        if channel_number < 4:
            cla = (cla & 0xBC) | channel_number
        elif channel_number < 20:
            secure = False if (cla & 0x0C) != 0 else True
            cla = (cla & 0xB0) | 0x40 | (channel_number - 4)
            if secure:
                cla = cla | 0x20
        else:
            raise ValueError("Specified channel number is out of range : " + channel_number)
        apdu = format(cla, '02X') + apdu[2:]

        return self.send_apdu_raw(apdu)

    def send_apdu(self, aid, apdu):
        channel_number = self.open_logical_channel()
        self.select_application(channel_number, aid)
        (response, sw) = self.send_apdu_on_channel(channel_number, apdu)
        self.close_logical_channel(channel_number)
        return (response, sw)

class OmapiTest(object):
    def __init__(self, commandif):
        self.commandif = commandif

    def testTransmitApdu(self, aid):
        print('started: ' + sys._getframe().f_code.co_name)

        # a. 0xA000000476416E64726F696443545331
        #   ii.The applet should return no data when it receives the following APDUs in Transmit:
        #         i.0x00060000
        #        ii.0x80060000
        #       iii.0xA0060000
        #        iv.0x94060000
        #         v.0x000A000001AA
        #        vi.0x800A000001AA
        #       vii.0xA00A000001AA
        #      viii.0x940A000001AA

        no_data_apdu_list = [
            '00060000',
            '80060000',
            'A0060000',
            '94060000',
            '000A000001AA',
            '800A000001AA',
            'A00A000001AA',
            '940A000001AA'
        ]

        for apdu in no_data_apdu_list:
            (response, sw) = self.commandif.send_apdu(aid, apdu)
            if len(response) > 0:
                raise RuntimeError('Unexpected output data is received : ' + response)
            if sw != '9000':
                raise RuntimeError('SW is not 9000 : ' + sw)

        # a. 0xA000000476416E64726F696443545331
        #   iii. The applet should return 256-byte data for the following Transmit APDUs:
        #         i.0x0008000000
        #        ii.0x8008000000
        #       iii.0xA008000000
        #        iv.0x9408000000
        #         v.0x000C000001AA00
        #        vi.0x800C000001AA00
        #       vii.0xA00C000001AA00
        #      viii.0x940C000001AA00

        data_apdu_list = [
            '0008000000',
            '8008000000',
            'A008000000',
            '9408000000',
            '000C000001AA00',
            '800C000001AA00',
            'A00C000001AA00',
            '940C000001AA00'
        ]

        for apdu in data_apdu_list:
            (response, sw) = self.commandif.send_apdu(aid, apdu)
            if len(response) != (256 * 2):
                raise RuntimeError('The length of output data is unexpected : ' + response)
            if sw != '9000':
                raise RuntimeError('SW is not 9000 : ' + sw)

        print('finished: ' + sys._getframe().f_code.co_name)

    def testLongSelectResponse(self, aid):
        print('started: ' + sys._getframe().f_code.co_name)

        channel_number = self.commandif.open_logical_channel()
        response = self.commandif.select_application_with_check_response(channel_number, aid)
        self.commandif.close_logical_channel(channel_number)

        print('finished: ' + sys._getframe().f_code.co_name)

    def testSegmentedResponseTransmit(self, aid):
        print('started: ' + sys._getframe().f_code.co_name)

        # a. 0xA000000476416E64726F696443545331
        #   v. The applet should return segmented responses with 0xFF as the last data byte and
        #      have the respective status words and response lengths for the following APDUs:
        #         i.0x00C2080000
        #        ii.0x00C4080002123400
        #       iii.0x00C6080000
        #        iv.0x00C8080002123400
        #         v.0x00C27FFF00
        #        vi.0x00CF080000
        #       vii.0x94C2080000

        segmented_response_apdu_list = [
            '00C2080000',
            '00C4080002123400',
            '00C6080000',
            '00C8080002123400',
            '00C27FFF00',
            '00CF080000',
            '94C2080000'
        ]

        for apdu in segmented_response_apdu_list:
            (response, sw) = self.commandif.send_apdu(aid, apdu)

            # P1 + P2 indicates the expected length of the output data.
            if len(response) != (int(apdu[4:8], 16) * 2):
                raise RuntimeError('Unexpected length of data is received : ' + str(len(response)))

            # The last data byte shall be 0xFF though the other bytes are not cared at all.
            if int(response[-2:], 16) != 0xFF:
                raise RuntimeError('Unexpected byte is received : ' + response[-2:])

            if sw != '9000':
                raise RuntimeError('SW is not 9000 : ' + sw)

        print('finished: ' + sys._getframe().f_code.co_name)

    def testStatusWordTransmit(self, aid):
        print('started: ' + sys._getframe().f_code.co_name)

        # a. 0xA000000476416E64726F696443545331
        #   iv. The applet should return the following status word responses
        #       for the respective Transmit APDU:
        #
        #       ... (see https://source.android.com/compatibility/cts/secure-element)
        #
        #       * The response should contain data that is the same as input APDU,
        #         except the first byte is 0x01 instead of 0x00.

        apdu_list = [
            '00F30006',
            '00F3000A01AA',
            '00F3000800',
            '00F3000C01AA00',
        ]

        warning_sw_list = [
                '6200', '6281', '6282', '6283', '6285', '62F1', '62F2', '63F1',
                '63F2', '63C2', '6202', '6280', '6284', '6286', '6300', '6381'
        ]

        for apdu in apdu_list:
            for p1 in range(0x10):
                apdu = apdu[:4] + format(p1 + 1, '02X') + apdu[6:]
                (response, sw) = self.commandif.send_apdu(aid, apdu)

                if sw.upper() != warning_sw_list[p1]:
                    raise RuntimeError('Unexpected warning SW : ' + sw)

                p2 = apdu[6:8]
                if p2 in {'06', '0A'}:
                    if len(response) > 0:
                        raise RuntimeError('Unexpected outgoing data : ' + response)
                elif p2 == '08':
                    if len(response) == 0:
                        raise RuntimeError('Outgoing data is expected')
                elif p2 == '0C':
                    if apdu[2:] != response[2:len(apdu)].upper():
                        raise RuntimeError('Outgoing data is different from APDU')
                else:
                    raise RuntimeError('Program error - P2 : ' + p2)

        print('finished: ' + sys._getframe().f_code.co_name)

    def testP2Value(self, aid):
        print('started: ' + sys._getframe().f_code.co_name)
        apdu = '00F40000'

        (response, sw) = self.commandif.send_apdu(aid, apdu)
        if response != '00':
            raise RuntimeError('Unexpected outgoing data : ' + response)
        if sw != '9000':
            raise RuntimeError('Unexpected status word : ' + sw)

        print('finished: ' + sys._getframe().f_code.co_name)

    def execute_all(self):

        selectable_aids = [
            'A000000476416E64726F696443545331',
            'A000000476416E64726F696443545332',
            'A000000476416E64726F696443545340',
            'A000000476416E64726F696443545341',
            'A000000476416E64726F696443545342',
            'A000000476416E64726F696443545343',
            'A000000476416E64726F696443545344',
            'A000000476416E64726F696443545345',
            'A000000476416E64726F696443545346',
            'A000000476416E64726F696443545347',
            'A000000476416E64726F696443545348',
            'A000000476416E64726F696443545349',
            'A000000476416E64726F69644354534A',
            'A000000476416E64726F69644354534B',
            'A000000476416E64726F69644354534C',
            'A000000476416E64726F69644354534D',
            'A000000476416E64726F69644354534E',
            'A000000476416E64726F69644354534F',
        ]

        for aid in selectable_aids:
            self.testTransmitApdu(aid)
            self.testLongSelectResponse(aid)
            self.testSegmentedResponseTransmit(aid)
            self.testStatusWordTransmit(aid)
            self.testP2Value(aid)

parser = argparse.ArgumentParser(description='Android Secure Element CTS')
parser.add_argument('-p', '--pcsc', nargs='?', const=0, type=int)
args = parser.parse_args()

transport = None
if args.pcsc is not None:
    transport = PcscSimLink(args.pcsc)
else:
    transport = PcscSimLink()

commandif = CommandInterface(transport)
transport.wait_for_card()
commandif.send_terminal_profile()

omapi = OmapiTest(commandif)
omapi.execute_all()


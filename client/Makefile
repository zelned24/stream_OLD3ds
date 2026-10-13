DEVKITPRO ?= /c/devkitPro
DEVKITARM ?= $(DEVKITPRO)/devkitARM
export DEVKITPRO DEVKITARM
include $(DEVKITARM)/3ds_rules

CXX := $(DEVKITARM)/bin/arm-none-eabi-g++
ARCH := -march=armv6k -mtune=mpcore -mfloat-abi=hard -mtp=soft
CXXFLAGS := -O2 -Wall -Wextra -std=gnu++17 $(ARCH) -I$(DEVKITPRO)/libctru/include
CXXFLAGS += -I$(DEVKITPRO)/portlibs/3ds/include
ifneq ($(SERVER_IP),)
CXXFLAGS += -DSTREAM_SERVER_IP='"$(SERVER_IP)"'
endif
LDFLAGS := -specs=3dsx.specs $(ARCH) -L$(DEVKITPRO)/libctru/lib
LDFLAGS += -L$(DEVKITPRO)/portlibs/3ds/lib

.PHONY: all clean
TARGET ?= rogue_stream
all: $(TARGET).3dsx
main.o: source/main.cpp source/panel.h source/panel_graphics.h source/media.h
	$(CXX) $(CXXFLAGS) -c $< -o $@
$(TARGET).elf: main.o
	$(CXX) $(LDFLAGS) $< -lturbojpeg -lctru -lm -o $@
$(TARGET).3dsx: $(TARGET).elf
	3dsxtool $< $@
clean:
	rm -f main.o rogue_stream.elf rogue_stream.3dsx
